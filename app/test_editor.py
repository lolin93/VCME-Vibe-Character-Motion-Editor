"""Host-side boundary tests; does not invoke a model or change research files."""
import unittest
from unittest.mock import MagicMock,patch
from types import SimpleNamespace
import server
from editor_api import validate,media
from selection import frame_count

class EditorTests(unittest.TestCase):
    def base(self):
        return dict(mode='select',media_id='sample',start=1,end=3.5,x=.5,y=.5,click_time=2)
    def test_durations(self):
        for duration,n in [(1,17),(1.125,21),(2.5,41),(3,49),(5,81),(10,161)]:
            self.assertEqual(frame_count(duration),n)
            self.assertEqual((n-1)%4,0)
    def test_select_nonfirst_frame(self):
        req=validate(self.base())
        self.assertEqual(req['duration'],2.5)
        self.assertEqual(req['frame_count'],41)
        self.assertEqual(req['source'],'/workspace/assets/source.mp4')
    def test_invalid_parameters(self):
        for values in [dict(start=float('nan')),dict(end=30),dict(start=0),dict(end=1.5),dict(x=1.1),dict(click_time=4),dict(seed=-1)]:
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate({**self.base(),**values})
    def test_generation_requires_selection(self):
        with self.assertRaises(ValueError):
            validate({**self.base(),'mode':'generate','motion':'wave'})
    def test_id_traversal_rejected(self):
        with self.assertRaises(ValueError):
            media('../assets')
    def test_recovered_job_checks_exit_status(self):
        for exit_text,expected in [('0\n','done'),('1\n','interrupted')]:
            job=MagicMock(); job.name='a'*32
            request_file=MagicMock();request_file.read_text.return_value='{"mode":"generate"}'
            output=MagicMock();output.is_file.return_value=True
            marker=MagicMock();marker.is_file.return_value=False
            job.__truediv__.side_effect=lambda name:{'request.json':request_file,'result.mp4':output,'completed.json':marker}[name]
            with patch.object(server.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=exit_text)) as run,patch.object(server,'status') as status:
                server.recover_worker(job)
                self.assertEqual(status.call_args.kwargs['state'],expected)
                self.assertEqual(run.call_args.args[0],['docker','wait','vcme-v58-job-'+job.name])

if __name__=='__main__':
    unittest.main()
