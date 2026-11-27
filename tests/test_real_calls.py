"""Found with a real wholesaler's Busy item list (pipes, fittings, pumps) and two
real phone calls. Sizes are part of the name, politeness is not a party, fares
are not lines, and "kal parson" is not a delivery day. Call lines are shortened
and names of people and places are taken out."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import catalog, db
from app.dialog import _short, build_draft
from app.main import app
from app.parser import parse_date
from app.textnorm import norm

client = TestClient(app)
PIPES = os.path.join(os.path.dirname(__file__), "fixtures", "pipe_items.csv")


@pytest.fixture
def pipe_shop():
    with open(PIPES, "rb") as f:
        r = client.post("/api/items/import?commit=1", files={"file": ("List of Items.csv", f.read(), "text/csv")})
    assert r.status_code == 200 and r.json()["count"] == 48
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())


@pytest.mark.parametrize("text,want", [
    ('Astral Elbow 3/4"', "astral elbow 0.75inch"),
    ("Astral Brass Ft Elbow 1*1/2", "astral bras ft elbow 1x0.5"),
    ("Astral Bush 1 1/2x1''", "astral bush 1.5x1inch"),
    ("Astral Elbow 1.5' 6kg ISI", "astral elbow 1.5inch 6kg isi"),
    ("Astral 40mm Elbow", "astral 40mm elbow"),
    ("Crompton Sumercible 1.5hp Water", "crompton sumercible 1.5hp water"),
    ("chaar by teen ke reducing elbow", "4x3 ke reducing elbow"),
    ("sawa inchi elbow tees", "1.25inch elbow tis"),
    ("pipe teen inch ke paanch heavy", "pipe 3inch ke panch heavy"),
    ("teen inch saadhe saat kilo ke paanch pipe", "3inch 7.5kg ke panch pipe"),
    ("dedh hp", "1.5hp"),
    ("das carton sabun", "das carton sabun"),
    ("5kg haldi", "5 kg haldi"),  # a quantity, not a pipe class
    ("10carton lux", "10 carton lux"),
])
def test_sizes_become_one_token(text, want):
    assert norm(text) == want


def _lines(text):
    d = build_draft(text)
    return [(ln["qty"], ln["unit"], ln["item"]["name"] if ln["item"] else None, ln["match"]) for ln in d["lines"]]


@pytest.mark.parametrize("text,want", [
    ("ABC ko 10 piece astral elbow 1 inch, 5 astral tee 3/4 inch",
     [(10, "piece", 'Astral Elbow 1"', "ok"), (5, "piece", 'Astral Tee 3/4"', "ok")]),
    ("ABC ko 20 astral socket 1/2 inch aur 4 end cap 1 inch",
     [(20, "piece", 'Astral Socket 1/2"', "ok"), (4, "piece", "Astral End Cap 1''", "ok")]),
    ("ABC ko astral union 2 inch 6 piece, astral bush 2 by 1 3 piece",
     [(6, "piece", "Astral Union 2'", "ok"), (3, "piece", "Astral Bush 2x1''", "ok")]),
    ("ABC ko 5 astral pipe sawa inch 6 kg isi", [(5, "piece", "Astral Pipe 1.25' 6kg ISI", "ok")]),
    ("ABC ko astral elbow do inch das", [(10, "piece", 'Astral Elbow 2"', "ok")]),
    ("ABC ko 12 astral ft elbow 1/2*1/2", [(12, "piece", "Astral Ft Elbow 1/2*1/2", "ok")]),
    ("ABC ko 8 astral tee 4 by 3", [(8, "piece", "Astral Tee 4x3'", "ok")]),
    ("ABC ko 4 crompton sumercible 1 hp oil", [(4, "piece", "Crompton Sumercible 1hp Oil", "ok")]),
    ("ABC ko sumercible dedh hp water 2 piece", [(2, "piece", "Crompton Sumercible 1.5hp Water", "ok")]),
    ("ABC ko 3 mini champ 1", [(3, "piece", "Crompton Mini Champ 1", "ok")]),
])
def test_sized_items_are_one_line(pipe_shop, text, want):
    assert _lines(text) == want


def test_one_inch_is_never_taken_for_two_inch(pipe_shop):
    d = build_draft("ABC ko 10 astral elbow 1 inch")
    assert d["lines"][0]["item"]["name"] == 'Astral Elbow 1"'


def test_size_beats_closer_letters(pipe_shop):
    d = build_draft("ABC ko teen inch elbow heavy do bag")  # "heavy" is not on the list: ask, 3" first
    assert d["lines"][0]["match"] == "unsure"
    assert d["lines"][0]["options"][0]["name"] == "Astral Elbow 3' 6kg ISI"


def test_item_said_as_not_there_is_not_a_line(pipe_shop):
    assert build_draft("ABC ko 10 astral tee 1 inch. To ye end cap do inch wale nahi hain")["lines"][1:] == []


def test_question_says_the_size(pipe_shop):
    d = build_draft("ABC ko 10 astral elbow")  # no size: ask, and the choices must sound different
    names = [o["name"] for o in d["question"]["options"]]
    assert len({_short(n) for n in names}) == len(names)
    assert _short("Fortune Refined Oil 1L") == "Fortune Refined Oil"


@pytest.mark.parametrize("text", ["Ji sahab.", "Haan ji sahab.", "Haan ji bhaiya.", "Ji sir ji bataiye."])
def test_politeness_is_not_a_party(text):
    assert build_draft(text + " 10 carton lux")["party"]["status"] == "missing"


def test_real_party_still_found():
    assert build_draft("Jain sahab ko 10 carton lux")["party"]["party"]["name"] == "Jain Brothers"


@pytest.mark.parametrize("text", [
    "Saadhe teen sau rupaye vahan ka.",
    "Phir yahan se dhaai sau rupaye vo lega vahan tak ka.",
    "Saadhe teen sau to vahan se kiraya lag jayega.",
])
def test_fares_are_not_lines(text):
    assert build_draft("ABC ko 10 carton lux. " + text)["lines"][1:] == []


def test_bundle_is_a_unit():
    d = build_draft("ABC ko 2 bundle lux")
    assert d["lines"][0]["unit"] == "bundle"


@pytest.mark.parametrize("text,label", [
    ("aage aur bhi bhejna ho kal parson", None),  # "in a day or two", not a day
    ("wo ek bundle to abhi yahan rakha hua hai", None),  # "abhi" in talk
    ("abhi bhej do", "aaj"),
    ("kal bhej dena", "kal"),
    ("kal nahi parso", "parso"),
])
def test_vague_days_are_not_a_delivery(text, label):
    d = parse_date(text)
    assert (d or {}).get("label") == label


CALL_1 = """Hello.
Haan ji sir ji bataiye.
Haan ji, haan ji, aapne saaman likhwa rakha tha, batao.
Wo ek bundle hai wo ISI wala pipe.
Ji sahab.
Aisa hi ka ek bundle to apne paas rakha hai.
Ek motor wale ka bhi order bhejna hai, pachaas motor baarah submersible.
Doosri baat, vo doosre chele ko to bhejo godam pe.
Ye kuch bundle aapke aur badh nahi sakte kya isme? Jaise ki maan lo aapko aage aur bhi bhejna ho kal parson.
Jo rickshaw ka kiraya hoga vo de denge hum.
Dekho bhaiya vahan se mangvaunga saadhe teen sau to vahan se kiraya lag jayega.
Saadhe teen sau rupaye vahan ka phir yahan se dhaai sau rupaye vo lega vahan tak ka.
Aur do chaar bundle aap bhi rakh lo aapke to bikte rehte honge.
Kitne bundle, kitne, chaar bundle bol doon to ho jayega?
Dekho bhaiya chhah bundle ka ek rickshaw hota hai.
Pooch lo. Baaki agar chaar bhi keh rahe ho aap to chaar mein bhi karva denge koi dikkat wali baat nahi.
Theek hai ji, main pooch ke batata hoon sir."""


def test_call_with_talk_guesses_nothing(pipe_shop):
    d = build_draft(CALL_1)
    assert d["party"]["status"] == "missing"  # "ji sahab" is not Jain Sahab
    assert d["delivery"] is None  # "kal parson" was talk
    heard = " / ".join(ln["heard"] for ln in d["lines"])
    for talk in ("rupaye", "kiraya", "rickshaw", "bikte", "karva", "bol dun"):
        assert talk not in heard
    assert all(not ln["item"] for ln in d["lines"])  # nothing guessed: every line asks
    qtys = [ln["qty"] for ln in d["lines"]]
    assert 50 in qtys and 12 in qtys  # "pachaas motor baarah submersible" stay for the staff to add
    assert 350 not in qtys and 250 not in qtys and 300 not in qtys


CALL_2 = """Pipe hain teen inch ke paanch heavy.
Elbow sawa inchi tees.
Sawa inchi elbow. Heavy wale kitne piece?
Tees.
Hand cap do inch ke das.
Ye. Nahi nahi, do inch wala nahi hai. Bas yahi de do bas sir. Theek hai, bhej de raha hoon. Kitne hain? Bhej do. Theek hai.
Aur aur kya iske alava?
Achha haan, chaar inch end cap kitne chahiye?
Haan ji, theek hai, sab likh liya, ye order poora ho gaya bhai ji."""


def test_sized_call_lines(pipe_shop):
    d = build_draft(CALL_2)
    got = [(ln["qty"], ln["item"]["name"] if ln["item"] else None) for ln in d["lines"]]
    assert (30, 'Astral Elbow 1 1/4"') in got  # "elbow sawa inchi tees"
    cap = next(ln for ln in d["lines"] if ln["qty"] == 10)  # "hand cap do inch ke das": asks, End Cap 2" first
    assert cap["match"] == "unsure" and cap["options"][0]["name"] == "Astral End Cap 2'"
    assert all(q not in (1.25, 2, 3, 4) for q, _ in got)  # a size is never a quantity
