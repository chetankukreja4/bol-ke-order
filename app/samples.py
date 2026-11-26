"""10 Hinglish test phrases with the expected result (used by tests and the demo chips)."""

TEST_PHRASES = [
    {"text": "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena",
     "expect": {"party": "P01", "lines": [("?soap", 10), ("OL01", 5)], "ask": "Kaun sa soap brand?"}},
    {"text": "Gupta ji ko das peti Lux aur pachees bori cheeni parso",
     "expect": {"party": "P04", "lines": [("SP01", 10), ("SG01", 25)]}},
    {"text": "Hello bhai kaise ho? Haan, Bittu store ke liye twenty five carton Maggi, rate thoda kam karo, aur 3 bori atta kal",
     "expect": {"party": "P05", "lines": [("MG01", 25), ("AT01", 3)]}},
    {"text": "Sharma ji ko 10 ya 12 carton Surf kal",
     "expect": {"party": "?", "lines": [("DT01", None)]}},
    {"text": "एबीसी को दस कार्टन लक्स और पांच बोरी चीनी कल भेज देना",
     "expect": {"party": "P01", "lines": [("SP01", 10), ("SG01", 5)]}},
    {"text": "Jain brothers, 4 carton Colgate, 2 carton Parle G, aaj hi",
     "expect": {"party": "P07", "lines": [("TP01", 4), ("BS01", 2)]}},
    {"text": "Punjab wale ko aath bori chawal aur dus carton sarson ka tel, Monday ko",
     "expect": {"party": "P06", "lines": [("RC01", 8), ("OL02", 10)]}},
    {"text": "Gupta kirana, chhe carton Tata namak, teen carton chai patti, discount 2 percent dena, kal",
     "expect": {"party": "P04", "lines": [("SL01", 6), ("TE01", 3)]}},
    {"text": "Bittu ko pandrah carton Dettol aur 7 carton Wheel, parso",
     "expect": {"party": "P05", "lines": [("SP03", 15), ("DT03", 7)]}},
    {"text": "ABC ke liye 4 carton xylo aur do carton ghee kal",
     "expect": {"party": "P01", "lines": [("?unknown", 4), ("GH01", 2)]}},
]
