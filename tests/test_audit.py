import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from emotion_recognition_claim_audit.audit import audit, evidence, main, matches, prose
from emotion_recognition_claim_audit.phrases import EMOTIONRECOGNITION, NOEMOTIONRECOGNITION, GENERIC_NAMES

EXPECTED_POS = ('emotion recognition', 'emotion-recognition', 'emotionrecognition', 'recognize emotions', 'recognizes emotions', 'recognizing emotions', 'recognize emotion', 'recognizes emotion', 'recognizing emotion', 'detect emotions', 'detects emotions', 'detecting emotions', 'detect emotion', 'detects emotion', 'detecting emotion', 'emotion recognition support', 'supports emotion recognition', 'emotion recognition capability', 'emotion recognition feature', 'emotion recognition pipeline', 'emotion recognition system', 'emotion recognition tool', 'emotion recognition framework', 'emotion recognition library', 'emotion recognition api', 'emotion recognition model', 'emotion recognition models', 'emotion recognition engine', 'emotion recognition module', 'emotion recognition function', 'emotion recognition functionality', 'emotion recognition workflow', 'emotion recognition method', 'emotion recognition approach', 'emotion recognition service', 'emotion recognition results', 'emotion recognition performance', 'emotion recognition task', 'emotion recognition tasks', 'emotion recognition algorithm', 'emotion recognition algorithms', 'emotion recognition configuration', 'emotion recognition script', 'emotion recognition mode', 'facial emotion recognition', 'facial-emotion recognition', 'speech emotion recognition', 'text emotion recognition', 'emotion detection', 'emotion classification')
EXPECTED_NEG = ('does not recognize emotions', 'do not recognize emotions', "doesn't recognize emotions", "don't recognize emotions", 'no emotion recognition', 'without emotion recognition', 'never recognizes emotions', 'does not support emotion recognition', 'emotion recognition not supported', 'emotion recognition unsupported', 'no emotion recognition support', 'lacks emotion recognition', 'missing emotion recognition', 'emotion recognition disabled', 'no emotion recognition model', 'without emotion recognition support', 'does not provide emotion recognition', 'no automatic emotion recognition', 'emotion recognition not available', 'no emotion recognition capability', 'does not detect emotions', 'without an emotion recognition model', 'does not perform emotion recognition', 'never performs emotion recognition')
EXPECTED_GENERIC = ('recognize_emotion', 'detect_emotion', 'predict_emotion', 'classify_emotion', 'emotion_recognition', 'analyze_emotion', 'emotion_detection', 'detect_emotions', 'predict_emotions', 'recognize_emotions', 'classify_emotions', 'emotion_classification', 'detect_facial_emotion', 'recognize_facial_emotion', 'facial_emotion_recognition', 'speech_emotion_recognition', 'text_emotion_recognition', 'emotion_analysis', 'analyze_emotions', 'predict_facial_emotion', 'classify_facial_emotion', 'emotion_predict', 'emotion_detect', 'get_emotion')

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = main(list(args))
            except SystemExit as error:
                code = error.code
        return code, output.getvalue()

    def test_phrase_oracle(self):
        self.assertEqual(EMOTIONRECOGNITION, EXPECTED_POS)
        self.assertEqual(NOEMOTIONRECOGNITION, EXPECTED_NEG)

    def test_generic_oracle(self):
        self.assertEqual(GENERIC_NAMES, EXPECTED_GENERIC)

    def test_all_phrases(self):
        for phrase in EXPECTED_POS:
            with self.subTest(phrase=phrase):
                self.put('README.md', phrase)
                found = audit(self.root)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]['phrase'], phrase)
        for phrase in EXPECTED_NEG:
            with self.subTest(denial=phrase):
                self.put('README.md', phrase)
                self.assertEqual(audit(self.root), [])
                self.put('feature.py', 'x.get_emotion()')
                self.assertEqual(audit(self.root)[0]['rule_id'], 'documented-no-emotion-recognition-claim-false')
                (self.root / 'feature.py').unlink()

    def test_span_and_case(self):
        self.put('README.md', 'does not recognize emotions')
        self.assertEqual(audit(self.root), [])
        for text in ('emotion recognition model', 'detect emotions'):
            self.assertEqual(len(matches(text, EMOTIONRECOGNITION)[1]), 1)
        for text in ('EMOTION RECOGNITION', 'she recognizes emotions better than words'):
            self.put('README.md', text)
            self.assertEqual(audit(self.root)[0]['severity'], 'HIGH')

    def test_fences_inline(self):
        self.put('README.md', '```text\nemotion recognition\n```')
        self.assertEqual(audit(self.root), [])
        self.put('README.md', '`emotion recognition`')
        self.assertEqual(len(audit(self.root)), 1)

    def test_cli(self):
        self.put('README.md', 'emotion recognition')
        code, output = self.cli('audit', str(self.root), '--json')
        self.assertEqual(code, 2)
        finding = json.loads(output)[0]
        self.assertEqual(finding['rule_id'], 'documented-emotion-recognition-claim-false')
        self.assertEqual(finding['severity'], 'HIGH')
        self.assertEqual(finding['verdict'], 'FAIL')
        self.assertTrue(finding['message'])
        self.assertEqual(self.cli('audit', str(self.root), '--ignore', 'README')[0], 0)
        self.put('feature.py', 'x.get_emotion()')
        self.assertEqual(self.cli('audit', str(self.root))[0], 0)
        self.put('README.md', 'no emotion recognition')
        code, output = self.cli('audit', str(self.root))
        self.assertEqual(code, 2)
        self.assertIn('documented-no-emotion-recognition-claim-false', output)
        self.assertIn('HIGH', output)
        self.put('README.md', 'ordinary prose')
        self.assertEqual(self.cli('audit', str(self.root))[0], 0)
        self.assertEqual(self.cli('--version'), (0, '0.1.0\n'))
        self.assertEqual(self.cli('bad')[0], 1)
        self.assertEqual(self.cli('audit', str(self.root / 'missing'))[0], 1)
        self.assertEqual(self.cli('audit', str(self.root), '--verbose')[0], 0)

    def test_test_only(self):
        self.put('tests/fixture.md', 'emotion recognition')
        self.assertEqual(audit(self.root)[0]['severity'], 'MEDIUM')
        self.assertEqual(self.cli('audit', str(self.root))[0], 0)
        self.assertEqual(self.cli('audit', str(self.root), '--fail-on', 'medium')[0], 2)

    def test_split_and_scope(self):
        self.put('README.md', 'emotion recognition')
        self.put('one.py', 'from hume import HumeClient\nc = HumeClient()')
        self.put('two.py', 'c.expression_measurement.batch.start()')
        self.assertEqual(len(audit(self.root)), 1)
        self.put('.venv/ignored.py', 'x.get_emotion()')
        self.put('.git/ignored.py', 'x.get_emotion()')
        self.assertEqual(len(audit(self.root)), 1)
        self.put('docs/guide.md', 'emotion classification')
        self.assertEqual(len(audit(self.root)), 2)

    def test_self_audit(self):
        readme = Path(__file__).resolve().parents[1] / 'README.md'
        self.assertTrue(readme.exists())
        self.put('README.md', readme.read_text())
        self.assertEqual(audit(self.root), [])

    def test_positive_00(self):
        self.assertTrue(evidence('import transformers as tf\ntf.pipeline("text-classification", model="Emotion-model")'))

    def test_positive_01(self):
        self.assertTrue(evidence('from transformers import pipeline as p\np("text-classification", model="emotion")'))

    def test_positive_02(self):
        self.assertTrue(evidence('import deepface as d\nd.DeepFace.analyze(x, actions=["EMOTION"])'))

    def test_positive_03(self):
        self.assertTrue(evidence('from deepface import DeepFace as D\nD.analyze(x, actions=("emotion",))'))

    def test_positive_04(self):
        self.assertTrue(evidence('from deepface import DeepFace\nDeepFace.analyze(x, actions={"emotion"})'))

    def test_positive_05(self):
        self.assertTrue(evidence('from fer import FER as F\nf=F()\nf.detect_emotions(x)'))

    def test_positive_06(self):
        self.assertTrue(evidence('import fer as f\nf.FER().detect_emotions(x)'))

    def test_positive_07(self):
        self.assertTrue(evidence('from hume import HumeClient as H\nc=H()\nc.expression_measurement.batch.start_inference_job(x)'))

    def test_positive_08(self):
        self.assertTrue(evidence('import hume\nhume.HumeBatchClient().expression_measurement.batch.start(x)'))

    def test_positive_09(self):
        self.assertTrue(evidence('from hume import HumeBatchClient\nc=HumeBatchClient()\nc.expression_measurement.start()'))

    def test_positive_10(self):
        self.assertTrue(evidence('x.recognize_emotion()'))

    def test_positive_11(self):
        self.assertTrue(evidence('from feature import recognize_emotion as f\nf()'))

    def test_positive_12(self):
        self.assertTrue(evidence('x.detect_emotion()'))

    def test_positive_13(self):
        self.assertTrue(evidence('from feature import detect_emotion as f\nf()'))

    def test_positive_14(self):
        self.assertTrue(evidence('x.predict_emotion()'))

    def test_positive_15(self):
        self.assertTrue(evidence('from feature import predict_emotion as f\nf()'))

    def test_positive_16(self):
        self.assertTrue(evidence('x.classify_emotion()'))

    def test_positive_17(self):
        self.assertTrue(evidence('from feature import classify_emotion as f\nf()'))

    def test_positive_18(self):
        self.assertTrue(evidence('x.emotion_recognition()'))

    def test_positive_19(self):
        self.assertTrue(evidence('from feature import emotion_recognition as f\nf()'))

    def test_positive_20(self):
        self.assertTrue(evidence('x.analyze_emotion()'))

    def test_positive_21(self):
        self.assertTrue(evidence('from feature import analyze_emotion as f\nf()'))

    def test_positive_22(self):
        self.assertTrue(evidence('x.emotion_detection()'))

    def test_positive_23(self):
        self.assertTrue(evidence('from feature import emotion_detection as f\nf()'))

    def test_positive_24(self):
        self.assertTrue(evidence('x.detect_emotions()'))

    def test_positive_25(self):
        self.assertTrue(evidence('from feature import detect_emotions as f\nf()'))

    def test_positive_26(self):
        self.assertTrue(evidence('x.predict_emotions()'))

    def test_positive_27(self):
        self.assertTrue(evidence('from feature import predict_emotions as f\nf()'))

    def test_positive_28(self):
        self.assertTrue(evidence('x.recognize_emotions()'))

    def test_positive_29(self):
        self.assertTrue(evidence('from feature import recognize_emotions as f\nf()'))

    def test_positive_30(self):
        self.assertTrue(evidence('x.classify_emotions()'))

    def test_positive_31(self):
        self.assertTrue(evidence('from feature import classify_emotions as f\nf()'))

    def test_positive_32(self):
        self.assertTrue(evidence('x.emotion_classification()'))

    def test_positive_33(self):
        self.assertTrue(evidence('from feature import emotion_classification as f\nf()'))

    def test_positive_34(self):
        self.assertTrue(evidence('x.detect_facial_emotion()'))

    def test_positive_35(self):
        self.assertTrue(evidence('from feature import detect_facial_emotion as f\nf()'))

    def test_positive_36(self):
        self.assertTrue(evidence('x.recognize_facial_emotion()'))

    def test_positive_37(self):
        self.assertTrue(evidence('from feature import recognize_facial_emotion as f\nf()'))

    def test_positive_38(self):
        self.assertTrue(evidence('x.facial_emotion_recognition()'))

    def test_positive_39(self):
        self.assertTrue(evidence('from feature import facial_emotion_recognition as f\nf()'))

    def test_positive_40(self):
        self.assertTrue(evidence('x.speech_emotion_recognition()'))

    def test_positive_41(self):
        self.assertTrue(evidence('from feature import speech_emotion_recognition as f\nf()'))

    def test_positive_42(self):
        self.assertTrue(evidence('x.text_emotion_recognition()'))

    def test_positive_43(self):
        self.assertTrue(evidence('from feature import text_emotion_recognition as f\nf()'))

    def test_positive_44(self):
        self.assertTrue(evidence('x.emotion_analysis()'))

    def test_positive_45(self):
        self.assertTrue(evidence('from feature import emotion_analysis as f\nf()'))

    def test_positive_46(self):
        self.assertTrue(evidence('x.analyze_emotions()'))

    def test_positive_47(self):
        self.assertTrue(evidence('from feature import analyze_emotions as f\nf()'))

    def test_positive_48(self):
        self.assertTrue(evidence('x.predict_facial_emotion()'))

    def test_positive_49(self):
        self.assertTrue(evidence('from feature import predict_facial_emotion as f\nf()'))

    def test_positive_50(self):
        self.assertTrue(evidence('x.classify_facial_emotion()'))

    def test_positive_51(self):
        self.assertTrue(evidence('from feature import classify_facial_emotion as f\nf()'))

    def test_positive_52(self):
        self.assertTrue(evidence('x.emotion_predict()'))

    def test_positive_53(self):
        self.assertTrue(evidence('from feature import emotion_predict as f\nf()'))

    def test_positive_54(self):
        self.assertTrue(evidence('x.emotion_detect()'))

    def test_positive_55(self):
        self.assertTrue(evidence('from feature import emotion_detect as f\nf()'))

    def test_positive_56(self):
        self.assertTrue(evidence('x.get_emotion()'))

    def test_positive_57(self):
        self.assertTrue(evidence('from feature import get_emotion as f\nf()'))

    def test_rejection_00(self):
        self.assertFalse(evidence('import transformers, deepface, fer, hume, cv2, mediapipe'))

    def test_rejection_01(self):
        self.assertFalse(evidence('from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer\na=SentimentIntensityAnalyzer()\na.polarity_scores(x)'))

    def test_rejection_02(self):
        self.assertFalse(evidence('from textblob import TextBlob\nTextBlob(x).sentiment'))

    def test_rejection_03(self):
        self.assertFalse(evidence('from transformers import pipeline\npipeline("sentiment-analysis", model="emotion")'))

    def test_rejection_04(self):
        self.assertFalse(evidence('import mediapipe as mp\nf=mp.solutions.face_mesh.FaceMesh()\nf.process(x)'))

    def test_rejection_05(self):
        self.assertFalse(evidence('import dlib\nd=dlib.get_frontal_face_detector()\nd(x)'))

    def test_rejection_06(self):
        self.assertFalse(evidence('import cv2\nc=cv2.CascadeClassifier()\nc.detectMultiScale(x)'))

    def test_rejection_07(self):
        self.assertFalse(evidence('track.classify_mood(x)'))

    def test_rejection_08(self):
        self.assertFalse(evidence('from fer import FER\nf=FER()'))

    def test_rejection_09(self):
        self.assertFalse(evidence('from hume import HumeClient\nc=HumeClient()'))

    def test_rejection_10(self):
        self.assertFalse(evidence('from hume import HumeBatchClient\nc=HumeBatchClient()'))

    def test_rejection_11(self):
        self.assertFalse(evidence('from deepface import DeepFace\nDeepFace.analyze(x, actions=["age", "gender"])'))

    def test_rejection_12(self):
        self.assertFalse(evidence('from deepface import DeepFace\nDeepFace.analyze(x)'))

    def test_rejection_13(self):
        self.assertFalse(evidence('from transformers import pipeline\npipeline("text-classification", model="sentiment-model")'))

    def test_rejection_14(self):
        self.assertFalse(evidence('classifier.predict(features)'))

    def test_rejection_15(self):
        self.assertFalse(evidence('"""emotion recognition"""\n# recognize emotions\nx="emotion recognition"'))

    def test_rejection_16(self):
        self.assertFalse(evidence('from feature import detect_emotion\ndetect_emotion'))

    def test_rejection_17(self):
        self.assertFalse(evidence('from feature import detect_emotion\ndef detect_emotion(): pass\ndetect_emotion()'))

    def test_rejection_18(self):
        self.assertFalse(evidence('from fer import FER\nclass FER: pass\nf=FER()\nf.detect_emotions(x)'))

    def test_rejection_19(self):
        self.assertFalse(evidence('import subprocess\nsubprocess.run(["recognize-emotions"])'))

    def test_rejection_20(self):
        self.assertFalse(evidence('from transformers import pipeline\ndef pipeline(*args, **kw): pass\npipeline("text-classification", model="emotion")'))

    def test_rejection_21(self):
        self.assertFalse(evidence('from hume import HumeClient\nclass HumeClient: pass\nc=HumeClient()\nc.expression_measurement.start()'))

    def test_rejection_22(self):
        self.assertFalse(evidence('from deepface import DeepFace\nclass DeepFace: pass\nDeepFace.analyze(x, actions=["emotion"])'))
