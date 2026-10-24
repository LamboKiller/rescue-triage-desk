import contextlib
import io
import json
import re
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.intake import to_fields
from app.agents.spans import validate
from app.config import ROOT
from app.data.source import LocalSource, ZetarisSource
from app.decide import decide
from app.geo.landmarks import match, normalize
from app.llm.nightshift import Nightshift
from support import Scratch
from test_core import TIME
from test_providers import Response
from tools.generate_messages import generate


def place(name="Estação Rodoviária de Porto Alegre", oid="1", **extra):
    result = dict(name=name, osm_type="node", osm_id=oid, municipality="Porto Alegre",
                alt_names="Rodoviária de Porto Alegre", neighbourhood="Centro", street="",
                category="amenity:bus_station", lat="-30", lon="-51",
                **{"in_water_2024-05-06": "1", "in_water_2024-05-08": "0"},  )
    result.update(extra)
    return result


class LandmarkTests(unittest.TestCase):
    def test_normalization_and_exact_over_contains(self):
        self.assertEqual(normalize("Estação Rodoviária de Porto Alegre"), "rodoviaria porto alegre")
        rows = [place(), place("Anexo da Rodoviária", "2", alt_names="")]
        result = match(rows, landmark_quote="rodoviaria de porto alegre", municipality="Porto Alegre")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["matched"]["osm_id"], "1")
        self.assertTrue(result["retrospective_water_overlap"])
        self.assertIsNone(match(rows, landmark_quote="rodoviaria", municipality="Porto Alegre", replay="2024-05-05")["observed_date"])

    def test_ambiguity_neighbourhood_and_city(self):
        a, b = place("Escola Aurora", "1"), place("Escola Aurora", "2")
        b["neighbourhood"] = "Norte"
        self.assertEqual(match([a,b], "Escola Aurora", municipality="Porto Alegre")["status"], "ambiguous")
        self.assertEqual(match([a,b], "Escola Aurora", municipality="Porto Alegre", neighbourhood="Norte")["matched"]["osm_id"], "2")
        self.assertEqual(match([a], "Escola Aurora", municipality="Curitiba")["status"], "unresolved")
        self.assertEqual(match([a], "Escola Aurora")["status"], "unresolved")

    def test_token_set_and_top_three(self):
        rows = [place("Escola Municipal Jardim das Flores", str(i)) for i in range(5)]
        result = match(rows, "Escola Municipal Jardim Flores", municipality="Porto Alegre")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 3)

    def test_decisions(self):
        fields = {k:{"value":v} for k,v in {"people":2,"municipality":"Porto Alegre","landmark":"Rodoviária"}.items()}
        location = {"found":False}
        lm = match([place()], "Rodoviária de Porto Alegre", municipality="Porto Alegre")
        result = decide(fields, location, TIME, TIME, landmark_location=lm)
        self.assertEqual(result["decision"], "SEND_CANDIDATE")
        self.assertEqual(result["questions"], [])
        self.assertIn("ponto de referência", result["location_confidence"])
        lm = match([place(),place(oid="2")], "Rodoviária de Porto Alegre", municipality="Porto Alegre")
        result = decide(fields, location, TIME, TIME, landmark_location=lm)
        self.assertEqual(result["decision"], "CALLBACK")
        self.assertIn("Rodoviária", result["questions"][0])
        result = decide(fields, location, TIME, TIME, landmark_location={"status":"unresolved"})
        self.assertIn("Qual o nome do lugar/bairro?", result["questions"])
        self.assertFalse(any("casa" in q for q in result["questions"]))

    def test_real_bus_station_if_present(self):
        rows = [r for r in LocalSource().landmarks() if r["municipality"] == "Porto Alegre" and r["category"] == "amenity:bus_station" and "rodoviaria" in normalize(r["name"])]
        if not rows:
            self.skipTest("No fetched bus station available")
        result = match(LocalSource().landmarks(), landmark_quote="rodoviaria de porto alegre", municipality="Porto Alegre")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["matched"]["category"], "amenity:bus_station")

    def test_zetaris_landmarks_table(self):
        with patch("app.data.source.Zetaris") as client:
            ZetarisSource().landmarks(timeout=4)
        self.assertEqual(client.return_value.rows.call_args.args, ("landmarks_v3",))


class IntakeEdgeTests(unittest.TestCase):
    def test_counts_and_evidence(self):
        for key,quote,expected in [("people","somos em quatro",4),("people","uma dúzia",12),
                                   ("people","meia dúzia",6), ("people","eu, minha mãe e meus 2 filhos",4),
                                   ("people","3 pessoas, na verdade somos 5",5),
                                   ("children","não tem criança",0),("pets","sem animais",0),
                                   ("children","bebê de colo",1),("disabled","minha vó não anda",1),
                                   ("elderly","minha vó não anda",1)]:
            with self.subTest(quote=quote):
                fields, rejected = validate(to_fields({key:quote}),quote)
                self.assertEqual(rejected,[])
                self.assertEqual(fields[key]["value"],expected)
        self.assertEqual(to_fields({"people":"muita gente"})["fields"],{})
        self.assertTrue(validate({"fields":{"people":{"value":9,"quote":"quatro"}}},"quatro")[1])


class RetryTests(unittest.TestCase):
    def test_invalid_then_valid_and_cap(self):
        def response(content):
            return Response(json.dumps({"choices":[{"message":{"content":content}}]}).encode())
        for contents, expected_calls, fails in [(["", "{}"],2,False),(["oops","oops"],2,True),(["[]"],1,False)]:
            scratch = Scratch()
            self.addCleanup(scratch.cleanup)
            with patch.dict("os.environ",{"NIGHTSHIFT_API_KEY":"TEST-ONLY"}), patch("time.sleep"), patch("urllib.request.urlopen",side_effect=[response(c) for c in contents]) as urlopen:
                client=Nightshift(Path(scratch.name)/"trace.jsonl")
                client.start_message("synthetic-retry")
                with contextlib.redirect_stdout(io.StringIO()):
                    if fails:
                        with self.assertRaises(RuntimeError): client.call("intake","test","test",time.monotonic()+180)
                    else: client.call("intake","test","test",time.monotonic()+180)
                self.assertEqual(urlopen.call_count,expected_calls)
                events=client.message_calls()
                self.assertEqual(len(events),expected_calls)
                self.assertEqual(events[0]["http_status"],200)
                if len(contents)>1: self.assertEqual(events[0]["detail"],"empty_or_invalid_json")


class DatasetTests(unittest.TestCase):
    def test_generator_grammar_and_truth(self):
        for seed in (7,101,202):
            messages,truth=generate(seed)
            self.assertEqual(len(messages),15)
            for m,t in zip(messages,truth):
                self.assertNotRegex(m["text"],r"\b1 (?:crianças|idosos|cachorros|acamados)\b")
                self.assertNotIn("pesssoas",m["text"])
                for k,noun in [("children","criança"),("elderly","idoso"),("pets","cachorro")]:
                    if k in t["expected_fields"]: self.assertIn(str(t["expected_fields"][k])+" "+noun,m["text"])

    def test_challenge_validity_and_coverage(self):
        messages=[json.loads(s) for s in (ROOT/"eval/challenge_set.jsonl").read_text(encoding="utf-8").splitlines()]
        truth=json.loads((ROOT/"eval/challenge_truth.json").read_text(encoding="utf-8"))
        self.assertEqual(len(messages),40)
        self.assertEqual({m["message_id"] for m in messages},{t["message_id"] for t in truth})
        self.assertEqual(len({m["message_id"] for m in messages}),40)
        tags={}
        for m,t in zip(messages,truth):
            self.assertTrue(m["synthetic"] and t["synthetic"])
            self.assertIsInstance(t["expected_fields"],dict)
            self.assertIn(t["expected_decision"],("CALLBACK","SEND_CANDIDATE","REPORTED_RESCUED"))
            self.assertNotRegex(m["text"],r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}[- ]?\d{2}(?!\d)")
            self.assertNotRegex(m["text"],r"(?<!\d)(?:\+?55\s*)?\(?\d{2}\)?[ -]?\d{4,5}[ -]?\d{4}(?!\d)")
            for tag in t["tags"]: tags[tag]=tags.get(tag,0)+1
        for tag in ("number_words","relations","negation","corrections","partial_rescue","famous_landmark","less_famous_landmark","audio","relayed","typos","out_of_area","injection","mixed_language","contradiction","indirect_vulnerability"):
            self.assertGreaterEqual(tags.get(tag,0),3,tag)
