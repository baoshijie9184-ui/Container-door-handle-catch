import hashlib
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import io
import zipfile

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
    def test_unreachable_raw_endpoint_uses_the_same_verified_git_blob(self):
        class ApiTransport(Transport):
            def get(self,url,limit):
                self.urls.append(url)
                raise ValueError('SOURCE_CONNECTION_FAILED')
            def document(self,url):
                if '/git/blobs/' not in url:return super().document(url)
                self.urls.append(url)
                digest=url.rsplit('/',1)[1]
                content=next(value for value in self.data.values() if hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest()==digest)
                if self.tamper and content==SKILL:content=b'X'+content[1:]
                return {'sha':digest,'size':len(content),'encoding':'base64','content':base64.encodebytes(content).decode()}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'package';transport=ApiTransport()
            result=module.download('https://github.com/fixtures/skills/tree/main/skills/fixture-reader',path,transport)
            self.assertTrue(result['downloaded']);self.assertEqual((path/'SKILL.md').read_bytes(),SKILL)
            self.assertEqual(len([u for u in transport.urls if '/git/blobs/' in u]),3)
            self.assertEqual(json.loads((path/'manifest.json').read_text())['commit'],COMMIT)
        with tempfile.TemporaryDirectory() as folder,self.assertRaisesRegex(ValueError,'REMOTE_BLOB_DIGEST_MISMATCH'):
            module.download('https://github.com/fixtures/skills/tree/main/skills/fixture-reader',Path(folder)/'package',ApiTransport(tamper=True))

    def test_blob_fallback_rejects_bad_identity_encoding_size_and_bytes(self):
        digest=hashlib.sha1(b'blob '+str(len(SKILL)).encode()+b'\0'+SKILL).hexdigest()
        entry={'path':'skills/fixture-reader/SKILL.md','sha':digest,'size':len(SKILL)}
        valid={'sha':digest,'size':len(SKILL),'encoding':'base64','content':base64.b64encode(SKILL).decode()}
        for changes in ({'sha':'b'*40},{'encoding':'text'},{'content':'!bad-base64!'},
                        {'size':len(SKILL)+1},{'size':module.MAX_FILE+1},{'size':True}):
            class Broken(Transport):
                def get(self,url,limit):raise ValueError('SOURCE_TIMEOUT')
                def document(self,url):return {**valid,**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):module.github_file(Broken(),'fixtures','skills',COMMIT,entry)

    def test_authentication_or_policy_failure_does_not_start_blob_fallback(self):
        class Denied(Transport):
            def get(self,url,limit):raise ValueError('SOURCE_AUTHENTICATION_REQUIRED')
            def document(self,url):raise AssertionError('No fallback is allowed for this failure')
        with self.assertRaisesRegex(ValueError,'SOURCE_AUTHENTICATION_REQUIRED'):
            module.github_file(Denied(),'fixtures','skills',COMMIT,{'path':'SKILL.md','sha':'a'*40})
        with self.assertRaisesRegex(ValueError,'REMOTE_BLOB_DIGEST_MISMATCH'):
            module.github_file(Denied(),'fixtures','skills',COMMIT,{'path':'SKILL.md','sha':'../commits/main'})

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
    def test_market_links_parse_without_inventing_or_hardcoding_upstream_git(self):
        self.assertEqual(module.source(module.MODEL_SCOPE_CREATOR),{'provider':'MODELSCOPE','id':'@anthropics/skill-creator'})
        self.assertEqual(module.source('https://modelscope.cn/skills/@other/example')['id'],'@other/example')
        self.assertEqual(module.source('https://skills.sh/fixtures/skills/fixture-reader')['provider'],'SKILLS_SH')
    def test_symlinks_and_git_blob_changes_fail_before_draft_creation(self):
        for transport in [Transport(symlink=True),Transport(tamper=True)]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):module.download('https://github.com/fixtures/skills/tree/main/skills/fixture-reader',Path(folder)/'package',transport)
    def test_windows_reserved_paths_case_duplicates_and_unknown_licenses_are_rejected(self):
        for value in ['../SKILL.md','scripts/CON.py','scripts//x.py','assets/name.','C:/outside','/absolute']:
            with self.assertRaises(ValueError):module.safe_path(value)
        with self.assertRaises(ValueError):module.license_type('All rights reserved')

class MarketTransport(Transport):
    def __init__(self, private=False, duplicate=False, symlink=False, license_content=LICENSE):
        super().__init__();self.private=private;self.duplicate=duplicate;self.archive_calls=0
        self.zip=io.BytesIO()
        with zipfile.ZipFile(self.zip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('snapshot/SKILL.md',SKILL);archive.writestr('snapshot/LICENSE.txt',license_content)
            script=zipfile.ZipInfo('snapshot/scripts/never-run.py');script.external_attr=(0o120777 if symlink else 0o100644)<<16
            archive.writestr(script,b'raise RuntimeError("DO_NOT_RUN")')
            if duplicate:archive.writestr('snapshot/other/SKILL.md',SKILL)
    def document(self,url):
        if 'modelscope.cn/openapi/' in url:
            return {'success':True,'data':{'id':'@fixtures/fixture-reader','private':self.private,'license':'','source_url':'https://github.com/unproven/repository'}}
        if url=='https://api.github.com/repos/fixtures/skills':return {'private':False,'default_branch':'main'}
        return super().document(url)
    def get(self,url,limit):
        if 'skills.sh' in url:return b'<a href="https://github.com/fixtures/skills">Source</a>'
        if 'modelscope.cn/skills/' in url:self.archive_calls+=1;return self.zip.getvalue()
        return super().get(url,limit)

class MarketSnapshotTest(unittest.TestCase):
    def test_skills_page_resolves_verified_repo_to_exact_commit_and_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'package';transport=MarketTransport()
            module.download('https://skills.sh/fixtures/skills/fixture-reader',target,transport)
            manifest=json.loads((target/'manifest.json').read_text())
            self.assertEqual(manifest['provider'],'SKILLS_SH');self.assertEqual(manifest['commit'],COMMIT)
            self.assertEqual(manifest['sourceIdentity'],'github:fixtures/skills/skills/fixture-reader')
            self.assertTrue(all(COMMIT in url for url in transport.urls))
    def test_unproven_page_repository_and_multiple_matching_directories_are_rejected(self):
        class Unproven(MarketTransport):
            def get(self,url,limit):return b'<a href="https://github.com/other/skills">Source</a>'
        class Duplicate(MarketTransport):
            def document(self,url):
                value=super().document(url)
                if '/git/trees/' in url:value['tree'].append({'path':'other/fixture-reader/SKILL.md'})
                return value
        for transport,reason in [(Unproven(),'MARKET_SOURCE_NOT_VERIFIED'),(Duplicate(),'SKILL_DIRECTORY_AMBIGUOUS')]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError,reason):module.download('https://skills.sh/fixtures/skills/fixture-reader',Path(folder)/'package',transport)
    def test_native_archive_keeps_original_bytes_metadata_and_content_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'package';transport=MarketTransport()
            result=module.download('https://modelscope.cn/skills/@fixtures/fixture-reader',target,transport)
            manifest=json.loads((target/'manifest.json').read_text())
            self.assertIsNone(manifest['commit']);self.assertEqual(manifest['revisionKind'],'CONTENT_SNAPSHOT')
            self.assertEqual((target/'_source/archive.zip').read_bytes(),transport.zip.getvalue())
            self.assertEqual(result['snapshotSha256'],hashlib.sha256(transport.zip.getvalue()).hexdigest())
            self.assertEqual(manifest['sourceVersion'],'snapshot-sha256:'+result['snapshotSha256'])
            self.assertTrue((target/'scripts/never-run.py').exists());self.assertFalse(manifest['scriptsExecutable'])
    def test_private_or_unknown_license_and_unsafe_native_archives_fail_closed(self):
        for transport,reason in [(MarketTransport(private=True),'PUBLIC_SKILL_METADATA_REQUIRED'),(MarketTransport(duplicate=True),'SKILL_DIRECTORY_AMBIGUOUS'),(MarketTransport(symlink=True),'LINKS_AND_SPECIAL_FILES_FORBIDDEN'),(MarketTransport(license_content=b'All rights reserved'),'SUPPORTED_LICENSE_REQUIRED')]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError,reason):module.download('https://modelscope.cn/skills/@fixtures/fixture-reader',Path(folder)/'package',transport)
                if transport.private:self.assertEqual(transport.archive_calls,0)
    def test_encoded_credentials_and_port_market_urls_are_rejected(self):
        for url in ['https://skills.sh:443/fixtures/skills/fixture-reader','https://skills.sh/fixtures/skills/%2e%2e','https://modelscope.cn/skills/@fixtures/fixture-reader?token=hidden','https://modelscope.cn@localhost/skills/@fixtures/fixture-reader']:
            with self.assertRaises(ValueError):module.source(url)

if __name__=='__main__':unittest.main()
