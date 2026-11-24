#!/usr/bin/env python3
"""Editable JSON -> PNG; no network calls and no modification of existing output."""
import argparse
import datetime as dt
import glob
import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, M = 1080, 76
INK, ORANGE, GREEN, LIME, PAPER = '#073c2d', '#ff590b', '#078d18', '#b8f13a', '#fffdf8'


def validate(e, final=False):
    for key in ('brand', 'edition', 'date', 'start', 'end', 'venue', 'fee', 'capacity'):
        if not isinstance(e.get(key), str) or not e[key].strip():
            raise ValueError(f'缺少字段: {key}')
    day = dt.date.fromisoformat(e['date'])
    weekday = '周' + '一二三四五六日'[day.weekday()]
    if e.get('weekday') and e['weekday'] != weekday:
        raise ValueError(f'日期与星期矛盾，应为{weekday}，请向用户确认')
    start, end = (dt.datetime.strptime(e[k], '%H:%M') for k in ('start', 'end'))
    if end <= start:
        raise ValueError('结束时间不晚于开始时间；跨日活动需另行确认排版')
    if not isinstance(e.get('topics'), list) or len(e['topics']) != 2:
        raise ValueError('本模板需要两组主题；其他结构请先调整模板')
    for topic in e['topics']:
        for key in ('label', 'description'):
            if not isinstance(topic.get(key), str) or not topic[key].strip():
                raise ValueError(f'主题缺少 {key}')
    if not isinstance(e.get('speakers'), list) or not 1 <= len(e['speakers']) <= 4:
        raise ValueError('本模板支持1至4位嘉宾')
    for s in e['speakers']:
        for key in ('name', 'title'):
            if not isinstance(s.get(key), str) or not s[key].strip():
                raise ValueError(f'嘉宾缺少 {key}')
        for key in ('company', 'role'):
            if not isinstance(s.get(key, ''), str):
                raise ValueError(f'嘉宾 {key} 必须是文字')
    if not isinstance(e.get('organizers'), list) or not e['organizers'] or any(
            not isinstance(s, str) or not s.strip() for s in e['organizers']):
        raise ValueError('缺少主办单位列表')
    if final:
        if e.get('confirmed') is not True or e.get('sample') is True:
            raise ValueError('正式稿需要用户确认，且不能是样板')
        visible = [e[k] for k in ('brand', 'edition', 'venue', 'fee', 'capacity')]
        visible += [v for t in e['topics'] for v in t.values() if isinstance(v, str)]
        visible += [v for s in e['speakers'] for v in s.values() if isinstance(v, str)]
        visible += e['organizers']
        if re.search(r'待确认|待填写|待定|样板|示例|TBD|分享嘉宾[一二三四]', '\n'.join(visible), re.I):
            raise ValueError('正式稿仍包含占位内容')
        if not e.get('qr'):
            raise ValueError('正式稿缺少报名二维码')
    return day, weekday


def font_source(path=None, index=None):
    if path:
        return Path(path).expanduser().resolve(), index or 0
    apple = sorted(glob.glob('/System/Library/AssetsV2/com_apple_MobileAsset_Font*/**/PingFang.ttc', recursive=True))
    candidates = [(Path(x), 7) for x in apple]
    candidates += [(Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'), 2),
                   (Path('/System/Library/Fonts/STHeiti Medium.ttc'), 1)]
    for p, i in candidates:
        if p.is_file():
            return p, i
    raise ValueError('未找到中文字体，请使用 --font 和 --font-index 指定；不会自动安装字体')


def qr_payload(im):
    try:
        import zxingcpp
    except ImportError as exc:
        raise ValueError('二维码校验需要 zxing-cpp，请安装 requirements.txt') from exc
    results = zxingcpp.read_barcodes(im)
    values = [x.text for x in results if x.format == zxingcpp.BarcodeFormat.QRCode]
    if len(values) != 1 or not values[0]:
        raise ValueError('必须提供一张可识别且只包含一个报名二维码的图片')
    return values[0]


def render(event, outdir, input_dir=Path('.'), font=None, font_index=None, final=False):
    day, weekday = validate(event, final)
    outdir = Path(outdir)
    if outdir.exists():
        raise ValueError('输出目录已存在，请为新版本指定新目录')
    fp, fi = font_source(font, font_index)
    fonts = {}
    def ft(n):
        if n not in fonts:
            fonts[n] = ImageFont.truetype(str(fp), n, index=fi)
        return fonts[n]
    # Fail clearly for missing font/asset before writing output.
    ft(32)
    art = Image.open(ROOT / 'assets/robots.png').convert('RGB')
    qr = None
    payload = None
    if event.get('qr'):
        qr = Image.open(Path(input_dir) / event['qr']).convert('RGB')
        payload = qr_payload(qr)
    im = Image.new('RGB', (W, 6000), PAPER)
    d = ImageDraw.Draw(im)
    layout = []

    def text(value, x, y, size=32, color=INK, max_width=None, max_lines=3, key=''):
        if not isinstance(value, str):
            raise ValueError(f'文字类型错误: {key}')
        width = max_width or W-M-x
        lines = []
        for paragraph in value.split('\n'):
            line = ''
            for char in paragraph:
                if d.textlength(char, font=ft(size)) > width:
                    raise ValueError(f'单个字超出可用宽度: {key}')
                if line and d.textlength(line+char, font=ft(size)) > width:
                    lines.append(line); line = char
                else:
                    line += char
            lines.append(line)
        if len(lines) > max_lines:
            raise ValueError(f'文字过长，需调整布局，不会截断: {key}')
        step = round(size*1.42)
        for i, line in enumerate(lines):
            d.text((x, y+i*step), line, font=ft(size), fill=color, anchor='lt')
        layout.append({'key': key, 'text': value, 'box': [x, y, x+width, y+len(lines)*step], 'font_size': size})
        return len(lines)*step

    def rule(y):
        d.line((M,y,W-M,y),fill=INK,width=2)
        return y+34

    y=48
    text(event['brand']+' · '+event['edition'],M,y,32,max_width=620,max_lines=1,key='brand')
    if not final:
        text('样板 · 非真实报名' if event.get('sample') else '预览 · 待确认',720,y+5,21,max_width=284,max_lines=1,key='draft')
    y+=84
    for i,t in enumerate(event['topics']):
        y+=text(t['label'],M,y,78,ORANGE if i==0 else GREEN,max_lines=1,key=f'topics.{i}.label')
        y+=text(t['description'],M,y,40,max_lines=2,key=f'topics.{i}.description')+22
    aw=W-2*M; ah=round(art.height*aw/art.width)
    im.paste(art.resize((aw,ah),Image.Resampling.LANCZOS),(M,y))
    y+=ah+25; y=rule(y)
    d.rectangle((M,y,M+7,y+144),fill=LIME)
    y+=text(f'{day.month}月{day.day}日 {weekday}',M+28,y,67,max_lines=1,key='date')
    timevalue=event['start']+' — '+event['end']
    tw=round(d.textlength(timevalue,font=ft(36)))
    d.rounded_rectangle((M+25,y,M+tw+61,y+58),radius=28,fill=LIME)
    text(timevalue,M+43,y+9,36,max_width=tw+8,max_lines=1,key='time')
    y+=84
    text('地点',M,y,31,max_width=85,max_lines=1,key='venue-label')
    y+=text(event['venue'],M+118,y,32,max_lines=3,key='venue')+30
    y=rule(y)
    y+=text('分享嘉宾',M,y,29,max_lines=1,key='speakers-label')+24
    for i,s in enumerate(event['speakers']):
        d.rectangle((M,y,M+6,y+52),fill=LIME)
        # Full width name avoids squeezing longer names beside organization.
        y+=text(s['name'],M+23,y,43,max_lines=2,key=f'speakers.{i}.name')
        desc=' '.join(x for x in (s.get('company',''),s.get('role','')) if x)
        if desc:
            y+=text(desc,M+23,y,27,max_lines=2,key=f'speakers.{i}.description')+5
        y+=text('《'+s['title']+'》',M+23,y,31,max_lines=3,key=f'speakers.{i}.title')+32
    y=rule(y)
    text('活动费用',M,y,27,max_width=265,max_lines=1,key='fee-label')
    text('活动规模',400,y,27,max_width=250,max_lines=1,key='capacity-label')
    text(event['fee'],M,y+60,41,max_width=285,max_lines=2,key='fee')
    text(event['capacity'],400,y+60,41,max_width=250,max_lines=2,key='capacity')
    d.line((365,y,365,y+170),fill=INK,width=1)
    qbox=(744,y,1004,y+260)
    if qr:
        thumb=qr.copy();thumb.thumbnail((236,236),Image.Resampling.NEAREST)
        d.rectangle(qbox,fill='white')
        im.paste(thumb,(744+(260-thumb.width)//2,y+(260-thumb.height)//2))
        if qr_payload(im.crop(qbox)) != payload:
            raise ValueError('成品二维码与原图解码不一致，拒绝输出')
    else:
        d.rounded_rectangle(qbox,radius=16,fill='white',outline='#b4c7bb',width=2)
        text('报名二维码\n待提供',770,y+85,29,max_width=218,max_lines=2,key='qr-placeholder')
    text('扫码报名' if qr else '样板不提供报名',744,y+277,24,max_width=260,max_lines=1,key='qr-label')
    y+=338;y=rule(y)
    y+=text('主办单位',M,y,29,max_lines=1,key='organizers-label')+18
    for i,org in enumerate(event['organizers']):
        y+=text(org,M,y,28,max_lines=2,key=f'organizers.{i}')+9
    y+=53
    if y>6000:
        raise ValueError('版面超出画布，需要调整模板')
    im=im.crop((0,0,W,y))
    outdir.mkdir(parents=True,exist_ok=False)
    im.save(outdir/'poster.png')
    saved=dict(event)
    if qr:
        qr.save(outdir/'qr.png');saved['qr']='qr.png'
    (outdir/'event.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (outdir/'layout.json').write_text(json.dumps(layout,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'mode':'final' if final else 'preview','text_source_sha256':hashlib.sha256(json.dumps(event,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'font':{'file':fp.name,'index':fi,'sha256':hashlib.sha256(fp.read_bytes()).hexdigest()},
            'size':[W,y], 'qr_check':'source_and_render_match' if qr else 'not_provided_preview_only',
            'visual_review':'pending_human_or_agent_review', 'poster_sha256':hashlib.sha256((outdir/'poster.png').read_bytes()).hexdigest()}
    (outdir/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--font');p.add_argument('--font-index',type=int)
    p.add_argument('--final',action='store_true')
    a=p.parse_args()
    try:
        e=json.loads(a.input.read_text(encoding='utf-8'))
        report=render(e,a.out,a.input.parent,a.font,a.font_index,a.final)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        p.exit(1,f'未完成：{exc}\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
