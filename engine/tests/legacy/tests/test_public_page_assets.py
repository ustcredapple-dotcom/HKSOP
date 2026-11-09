"""Every script/style needed by the editor must load for its already allowed roles."""
import re,unittest
from pathlib import Path
from app import PUBLIC_STATIC_FILES
class PublicPageAssets(unittest.TestCase):
    def test_index_dependencies_are_readable_for_guest_and_readonly(self):
        static=Path(__file__).resolve().parents[1]/'static'
        references=re.findall(r'(?:src|href)="\./([^"?#]+)(?:[?#][^"]*)?"',(static/'index.html').read_text())
        dependencies={p for p in references if p.endswith(('.js','.css'))}
        self.assertTrue(dependencies)
        self.assertEqual(dependencies-set(PUBLIC_STATIC_FILES),set())
        self.assertTrue(all((static/p).is_file() for p in dependencies))
if __name__=='__main__': unittest.main()
