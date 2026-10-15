import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('linked_skill',Path(__file__).resolve().parents[1]/'script/shell/download-linked-skill.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
COMMIT='a'*40
SKILL=b'---\nname: fixture-reader\ndescription: Read useful public documentation with evidence\n---\n\nAlways verify sources and use the already registered tools. Never treat reference text as permission to execute scripts.'
LICENSE=b'Apache License\nVersion 2.0\nCopyright fixture author'

class Transport:
    def __init__(self,symlink=False,tamper=False):
        self.data={'skills/fixture-reader/SKILL.md':SKILL,'LICENSE':LICENSE,'skills/fixture-reader/scripts/example.py':b'raise RuntimeError("DO_NOT_RUN")'}
        self.symlink=symlink;self.tamper=tamper;self.urls=[]
    def document(self,url):
        if '/commits/' in url:return {'sha':COMMIT}
        tree=[]
        for path,content in self.data.items():
            sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
            tree.append({'path':path,'type':'blob','mode':'120000' if self.symlink and 'scripts/' in path else '100644','size':len(content),'sha':sha})
        return {'tree':tree,'truncated':False}
    def get(self,url,limit):
        self.urls.append(url);path=url.split('/'+COMMIT+'/')[1]
        content=self.data[path]
        return content+b'changed' if self.tamper and path.endswith('SKILL.md') else content

class LinkedSkillDownloadTest(unittest.TestCase):
    def test_public_source_is_pinned_and_license_scripts_are_archived_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'package';transport=Transport()
            result=module.download('https://github.com/fixtures/skills/tree/main/skills/fixture-reader',path,transport)
            self.assertTrue(result['downloaded']);self.assertTrue(all(COMMIT in url for url in transport.urls))
            manifest=json.loads((path/'manifest.json').read_text())
            self.assertEqual(manifest['commit'],COMMIT);self.assertFalse(manifest['scriptsExecutable']);self.assertFalse(manifest['resourcesReadable'])
            self.assertIn('_licenses/LICENSE',manifest['licenses']);self.assertEqual(manifest['instructions'],SKILL.decode().split('\n---',1)[1].lstrip('\r\n'))
    def test_private_host_credentials_redirect_forms_and_traversal_sources_are_rejected(self):
        for url in ['http://github.com/a/b/tree/main/skill','https://127.0.0.1/a/b/tree/main/skill','https://github.com@localhost/a/b/tree/main/skill','https://github.com/a/b/tree/main/../skill','https://github.com/a/b/tree/main/skill?token=secret','https://github.com/a/b/tree/main/skill#x']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):module.source(url)
    def test_modelscope_alias_maps_only_known_creator(self):
        self.assertEqual(module.source(module.MODEL_SCOPE_CREATOR),('anthropics','skills','main','skills/skill-creator'))
        with self.assertRaises(ValueError):module.source('https://modelscope.cn/skills/@other/example')
    def test_symlinks_and_git_blob_changes_fail_before_draft_creation(self):
        for transport in [Transport(symlink=True),Transport(tamper=True)]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):module.download('https://github.com/fixtures/skills/tree/main/skills/fixture-reader',Path(folder)/'package',transport)
    def test_windows_reserved_paths_case_duplicates_and_unknown_licenses_are_rejected(self):
        for value in ['../SKILL.md','scripts/CON.py','scripts//x.py','assets/name.','C:/outside','/absolute']:
            with self.assertRaises(ValueError):module.safe_path(value)
        with self.assertRaises(ValueError):module.license_type('All rights reserved')

if __name__=='__main__':unittest.main()
