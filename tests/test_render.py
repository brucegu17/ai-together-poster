import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('render',ROOT/'scripts/render.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class PosterTests(unittest.TestCase):
    def setUp(self):
        self.e=json.loads((ROOT/'examples/sample.json').read_text())

    def test_conflicting_weekday_rejected(self):
        self.e['weekday']='周一'
        with self.assertRaisesRegex(ValueError,'矛盾'):r.validate(self.e)

    def test_unconfirmed_or_placeholder_cannot_be_final(self):
        with self.assertRaisesRegex(ValueError,'确认'):r.validate(self.e,True)
        self.e.update(confirmed=True,sample=False)
        with self.assertRaisesRegex(ValueError,'占位'):r.validate(self.e,True)

    def test_no_actual_registration_in_sample(self):
        self.assertIsNone(self.e['qr'])
        self.assertTrue(self.e['sample'])
        self.assertTrue(all(not s['company'] for s in self.e['speakers']))

    def test_single_name_edit_is_local(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/'a',Path(td)/'b'
            r.render(self.e,a)
            changed=copy.deepcopy(self.e);changed['speakers'][0]['name']='分享嘉宾甲'
            r.render(changed,b)
            before=Image.open(a/'poster.png');after=Image.open(b/'poster.png')
            self.assertEqual(before.size,after.size)
            diff=ImageChops.difference(before,after)
            self.assertIsNotNone(diff.getbbox())
            box=next(x['box'] for x in json.loads((a/'layout.json').read_text()) if x['key']=='speakers.0.name')
            ImageDraw.Draw(diff).rectangle(box,fill=(0,0,0))
            self.assertIsNone(diff.getbbox())

    def test_long_text_fails_instead_of_truncating(self):
        self.e['topics'][0]['label']='超长主题'*50
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'long'
            with self.assertRaisesRegex(ValueError,'过长'):r.render(self.e,out)
            self.assertFalse(out.exists())

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'已存在'):r.render(self.e,Path(td))


if __name__=='__main__':unittest.main()
