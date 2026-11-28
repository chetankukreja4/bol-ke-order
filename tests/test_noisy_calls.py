"""Two-person shop calls (call recordings, pasted call transcripts): prices, pack sizes,
delivery times, totals, the shop repeating the order back, and later changes. One real
noisy test call (tests/fixtures/noisy_call_ansari.txt, Sarvam saaras:v4 translit) and
18 made-up calls in the same style: 6 used while writing the rules and 12 written
afterwards as unseen checks (7 of 12 were right on first run; all are now)."""
import os
import tempfile
from datetime import timedelta

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest

from app import catalog
from app.dialog import build_draft
from app.parser import today

HERE = os.path.dirname(__file__)


@pytest.fixture(autouse=True)
def sample_lists():
    catalog.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])


def got(d):
    party = d["party"]["party"]["code"] if d["party"]["status"] == "ok" else None
    lines = [(ln["item"]["code"] if ln["match"] == "ok" else None, ln["qty"], ln["unit"]) for ln in d["lines"]]
    return party, lines, (d["delivery"] or {}).get("date")


def test_real_noisy_call():
    with open(os.path.join(HERE, "fixtures", "noisy_call_ansari.txt"), encoding="utf-8") as f:
        d = build_draft(f.read(), call=True)
    party, lines, when = got(d)
    assert party is None  # Ansari Traders / Delta X is not on the list: ask
    assert lines == [("GH01", 10, "carton"), ("SP01", 12, "carton"), ("AT01", 4, "bag"), ("SL01", 30, "carton")]
    assert when == (today() + timedelta(days=2)).isoformat()
    assert not any(ln["qty"] in (500, 490, 2000) for ln in d["lines"])  # prices are never quantities


CALLS = [
    ('price_pack_echo', 'Hello.\nHaan ji Gupta ji bolo.\nBhai Surf Excel ka rate kya chal raha hai aajkal?\nSurf ka 95 rupaye packet hai, carton mein 24 packet aate hain.\nAchha. To 20 carton Surf bhej do.\n20 carton Surf Excel, theek hai.\nAur Tide bhi chahiye, Tide ka kya bhav hai?\nTide 110 ka padega.\nTheek hai Tide 5 carton.\nPaanch carton Tide. Aur kuch?\nBas. Do din mein aa jayega na?\nHaan kal hi bhej denge.\nTheek hai kal.',
     'P04', [('DT01', 20, 'carton'), ('DT02', 5, 'carton')], 1),
    ('later_change_and_item_count', 'Haan bhai Bittu bol raha hoon.\nHaan Bittu bhai bolo.\nCheeni likho paanch bori.\nPaanch bori cheeni.\nAur chawal teen bori basmati.\nTeen bori chawal.\nNahi yaar cheeni aath kar do, paanch kam padegi.\nTheek hai cheeni aath bori.\nTo total do item ho gaye.\nHaan bas itna hi.\nKab chahiye?\nParso tak bhej dena.\nTheek hai parso.',
     'P05', [('SG01', 8, 'bag'), ('RC01', 3, 'bag')], 2),
    ('price_descriptor_thousands', 'Namaste ABC Traders se bol raha hoon.\nHaan ji bataiye.\nMaggi chahiye pachas packet, woh 12 rupaye wala.\nPachas packet Maggi.\nAur Parle G 5 rupaye wala das carton.\nDas carton Parle G. Pura maal lagbhag teen hazaar ka padega.\nTheek hai. Aur ek carton mein kitne Parle G hote hain?\nEk carton mein 48 hote hain.\nAchha theek hai. Kal bhej dena.\nHaan kal pakka.',
     'P01', [('MG01', 50, 'packet'), ('BS01', 10, 'carton')], 1),
    ('question_then_answer', 'Hello Jain sahab.\nHaan bolo bhai.\nDettol sabun bhejna hai.\nDettol kitne?\nPandrah peti.\nPandrah peti Dettol, theek.\nAur Colgate?\nColgate chaar carton kar do.\nChaar carton Colgate.\nDelivery aaj ho jayegi?\nAaj nahi, kal subah.\nTheek hai kal.',
     'P07', [('SP03', 15, 'carton'), ('TP01', 4, 'carton')], 1),
    ('weights_and_sizes', 'Haan New Punjab Stores?\nHaan ji.\nPachas kilo wali bori cheeni chaar.\nChaar bori cheeni pachas kilo wali.\nAur atta das kilo wala chhah bori.\nChhah bori atta.\nGhee ka rate? 550 rupaye litre.\nTheek hai Amul ghee do carton.\nDo carton ghee.\nKab tak? Teen chaar din lagenge kya?\nNahi parso de denge.\nTheek hai.',
     'P06', [('SG01', 4, 'bag'), ('AT01', 6, 'bag'), ('GH01', 2, 'carton')], 2),
    ('noisy_repeats', 'Hello hello awaaz aa rahi hai?\nHaan haan bolo bolo.\nGupta ji bol raha hoon.\nHaan Gupta ji.\nDas das carton Lux aur Lifebuoy.\nDas carton Lux, das carton Lifebuoy.\nHaan haan.\nAur namak bhi Tata namak saat carton.\nSaat carton Tata namak.\nTotal kitne carton ho gaye?\nTotal sattais carton.\nTheek hai. Kal bhej dena.\nKal pakka bhej denge.',
     'P04', [('SP01', 10, 'carton'), ('SP02', 10, 'carton'), ('SL01', 7, 'carton')], 1),
    ('h_price_then_order', 'Hello Sharma General Store?\nHaan ji bolo.\nBhaiya Wheel powder ka kya chal raha hai?\nWheel 60 rupaye ka ek, carton 2400 ka.\nTheek hai, aath carton Wheel.\nAath carton Wheel powder.\nAur ek peti mein kitne packet hote hain? Chalis hote hain.\nAchha. Aur Tata chai teen carton.\nTeen carton chai.\nKal mil jayega? Haan kal.',
     'P03', [('DT03', 8, 'carton'), ('TE01', 3, 'carton')], 1),
    ('h_change_mind', 'ABC Traders bol raha hoon.\nHaan ji.\nMoong dal do bori likh lo.\nDo bori moong dal.\nAur toor dal bhi do bori.\nDo bori toor.\nEk kaam karo, toor dal teen kar do.\nTeen bori toor dal theek hai.\nDelivery parso.\nParso ho jayegi.',
     'P01', [('DL02', 2, 'bag'), ('DL01', 3, 'bag')], 2),
    ('h_asked_quantity', 'Bittu store se.\nHaan Bittu bhai.\nSarson ka tel chahiye.\nKitna chahiye?\nBarah carton.\nBarah carton sarson tel.\nAur machis?\nMachis bees packet.\nBees packet machis. Rate wahi 2 rupaye wala.\nHaan. Aaj shaam tak bhej do, aaj hi.\nTheek hai aaj.',
     'P05', [('OL02', 12, 'carton'), ('MC01', 20, 'packet')], 0),
    ('h_days_and_money', 'Jain Brothers.\nHaan ji bataiye.\nFortune oil das carton.\nDas carton Fortune.\nKitne din mein aayega? Paanch din mein?\nNahi bhai teen din mein aa jayega, parso bhi ho sakta hai.\nParso hi bhejo. Kitne ka hoga total?\nTotal pandrah hazaar ka.\nTheek hai.',
     'P07', [('OL01', 10, 'carton')], 2),
    ('h_total_of_item', 'Gupta kirana.\nHaan ji.\nLux chaar peti, pink wala do peti alag se.\nChaar peti Lux aur do peti pink.\nTo Lux total chhah peti ho gaya.\nHaan chhah.\nAur cheeni do bori.\nDo bori cheeni.\nKal.',
     'P04', [('SP01', 6, 'carton'), ('SG01', 2, 'bag')], 1),
    ('g_rate_first', 'Hello ABC Traders?\nHaan ji boliye.\nBasmati chawal ka bhav kya hai abhi?\nPachchis kilo ki bori 1800 ki pad rahi hai.\nThoda zyada hai. Chalo do bori de do.\nDo bori basmati.\nAur moong dal ek bori.\nEk bori moong.\nKal tak aa jayega?\nHaan kal pahuncha denge.',
     'P01', [('RC01', 2, 'bag'), ('DL02', 1, 'bag')], 1),
    ('g_recount', 'Gupta ji bol rahe hain.\nJi Gupta ji.\nColgate teen carton, Lux do carton.\nTeen Colgate, do Lux.\nNahi Lux do nahi, chaar carton.\nAchha Lux chaar.\nAur Dettol ek carton mein kitne aate hain? Ek carton mein 72 aate hain.\nTheek hai Dettol rehne do.\nParso bhejna.',
     'P04', [('TP01', 3, 'carton'), ('SP01', 4, 'carton')], 2),
    ('g_shop_asks', 'Haan Bittu bhai.\nBhai order hai.\nBolo kya kya.\nTata salt.\nKitne carton?\nDas.\nDas carton Tata salt.\nAur chai patti paanch carton, 1 kilo wali.\nPaanch carton chai. Aur kuch?\nNahi bas, kal subah.',
     'P05', [('SL01', 10, 'carton'), ('TE01', 5, 'carton')], 1),
    ('g_days_noise', 'Jain brothers se bol raha hoon.\nHaan ji bolo.\nMaggi tees carton.\nTees carton Maggi. Ek carton mein 96 packet aate hain bata deta hoon.\nTheek hai. Kitne din lagenge?\nDo teen din lagenge.\nTheek hai, parson tak kar dena.\nOk parso.',
     'P07', [('MG01', 30, 'carton')], 2),
    ('k_mixed', 'Hello, New Punjab Stores?\nHaan ji.\nSir Surf ka naya rate aaya hai kya?\nHaan 10 rupaye badh gaya, ab 105 ka hai.\nKoi baat nahi, Surf aath carton aur Wheel chaar carton.\nAath Surf, chaar Wheel.\nWheel paanch kar do.\nTheek hai Wheel paanch.\nKal bhejoge?\nHaan kal.',
     'P06', [('DT01', 8, 'carton'), ('DT03', 5, 'carton')], 1),
    ('k_ghee_cans', 'Sharma Traders.\nHaan bhai.\nAmul ghee ke can chahiye.\nKitne carton?\nDo carton. Ek carton mein kitne can hote hain?\nEk carton mein 12 can hote hain, matlab 24 can ho jayenge.\nTheek hai. Aur Fortune oil teen carton.\nTeen carton Fortune.\nParso.\nTheek hai parso.',
     'P02', [('GH01', 2, 'carton'), ('OL01', 3, 'carton')], 2),
    ('k_haggle', 'Bittu store.\nHaan ji.\nAtta das bori chahiye.\nDas bori atta. Rate 420 bori.\n400 lagao na.\nChalo 410 kar dete hain.\nTheek hai. Aur cheeni paanch bori.\nPaanch bori cheeni.\nAaj bhej do.\nAaj shaam tak.',
     'P05', [('AT01', 10, 'bag'), ('SG01', 5, 'bag')], 0),
]


@pytest.mark.parametrize("name,text,party,lines,days", CALLS, ids=[c[0] for c in CALLS])
def test_shop_calls(name, text, party, lines, days):
    assert got(build_draft(text, call=True)) == (party, lines, (today() + timedelta(days=days)).isoformat())
