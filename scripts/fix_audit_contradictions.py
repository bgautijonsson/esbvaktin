"""Fix high-severity contradictions found by evidence audit.

Run with: uv run python scripts/fix_audit_contradictions.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

CHANGED_IDS: list[str] = []


def connect():
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    return conn


def update_entry(
    conn,
    evidence_id: str,
    *,
    statement: str | None = None,
    caveats: str | None = None,
    statement_is: str | None = None,
    caveats_is: str | None = None,
    confidence: str | None = None,
    subtopic: str | None = None,
):
    """Update a DB entry and reset proofreading hash."""
    sets = []
    params = []

    for field, val in [
        ("statement", statement),
        ("caveats", caveats),
        ("statement_is", statement_is),
        ("caveats_is", caveats_is),
        ("confidence", confidence),
        ("subtopic", subtopic),
    ]:
        if val is not None:
            sets.append(f"{field} = %s")
            params.append(val)

    if not sets:
        return

    # Always reset proofreading hash
    sets.append("is_proofread_hash = NULL")

    params.append(evidence_id)
    sql = f"UPDATE evidence SET {', '.join(sets)} WHERE evidence_id = %s"
    cur = conn.cursor()
    cur.execute(sql, params)
    count = cur.rowcount
    if count == 0:
        print(f"  WARNING: {evidence_id} not found in DB!")
    else:
        print(f"  Updated {evidence_id} ({count} row)")
    CHANGED_IDS.append(evidence_id)


def fix_curr_data_003(conn):
    """Fix inflation peak figure — clarify 18.6% is Jan 2009 YoY, not annual average."""
    print("\n--- CURR-DATA-003: Inflation peak clarification ---")
    update_entry(
        conn,
        "CURR-DATA-003",
        statement=(
            "Iceland has experienced significantly higher and more volatile inflation "
            "than the eurozone over the past two decades. Average annual CPI inflation "
            "in Iceland was approximately 5.5% over 2005–2025, compared to approximately "
            "2.1% in the eurozone over the same period. Iceland's annual average CPI "
            "inflation peaked at 12.7% in 2008 during the financial crisis (the 12-month "
            "year-on-year reading reached 18.6% in January 2009) and reached 10.2% in "
            "2022–2023 during the global inflation surge. The eurozone peaked at 10.6% "
            "in October 2022 but returned below 3% by late 2023, while Icelandic "
            "inflation remained above 6% through most of 2024."
        ),
        statement_is=(
            "Verðbólga á Íslandi hefur verið mun hærri og sveiflukenndari en á "
            "evrusvæðinu síðustu tvo áratugi. Meðalverðbólga á Íslandi var um 5,5% á "
            "árunum 2005–2025 samanborið við 2,1% á evrusvæðinu. Meðalársverðbólga náði "
            "hámarki í 12,7% árið 2008 í fjármálakreppunni (12 mánaða breytingin fór "
            "hæst í 18,6% í janúar 2009) og 10,2% árið 2022–2023."
        ),
    )


def fix_curr_data_004(conn):
    """Fix CBI rate from 8.0% to 7.25%."""
    print("\n--- CURR-DATA-004: CBI rate 8.0% → 7.25% ---")
    update_entry(
        conn,
        "CURR-DATA-004",
        statement=(
            "The Central Bank of Iceland's policy rate has consistently been significantly "
            "higher than the European Central Bank's rate. As of early 2026, the CBI policy "
            "rate stood at 7.25%, compared to the ECB's deposit facility rate of approximately "
            "2.75%. This ~4.5 percentage point gap is typical — over the 2000–2025 period, "
            "the CBI rate averaged approximately 6.5% versus the ECB's ~1.5%. The CBI cut "
            "rates by a cumulative 2.0 percentage points from 9.25% starting in mid-2025, "
            "reaching 7.25% by March 2026. If Iceland adopted the euro, Icelandic borrowers "
            "would benefit from lower base rates, though a convergence premium would likely "
            "apply during a transition period."
        ),
        statement_is=(
            "Stýrivextir Seðlabanka Íslands hafa stöðugt verið mun hærri en vextir "
            "Seðlabanka Evrópu. Í byrjun árs 2026 voru stýrivextir á Íslandi 7,25% "
            "samanborið við ~2,75% hjá ESB — um 4,5 prósentustiga bil. Seðlabankinn "
            "lækkaði vexti um samtals 2,0 prósentustig frá 9,25% og náðu þeir 7,25% "
            "í mars 2026."
        ),
    )


def fix_currency_data_015(conn):
    """Fix CBI rate from 8.5% to 7.25%."""
    print("\n--- CURRENCY-DATA-015: CBI rate 8.5% → 7.25% ---")
    update_entry(
        conn,
        "CURRENCY-DATA-015",
        statement=(
            "The Central Bank of Iceland has consistently maintained higher interest rates "
            "than the European Central Bank. The CBI's key rate has averaged approximately "
            "6.5% over the 2000–2025 period, compared to the ECB's average of approximately "
            "1.5%. As of early 2026, the CBI rate stood at 7.25% (after cumulative 2.0 "
            "percentage point cuts from 9.25%) while the ECB deposit facility rate was "
            "approximately 2.75%. This differential reflects Iceland's higher inflation, "
            "currency risk premium, and the CBI's need to defend the króna."
        ),
        statement_is=(
            "Seðlabanki Íslands hefur stöðugt haldið hærri vöxtum en Seðlabanki Evrópu. "
            "Meðalstýrivextir á Íslandi voru um 6,5% á árunum 2000–2025 á móti ~1,5% hjá "
            "ESB. Í byrjun árs 2026 voru stýrivextir á Íslandi 7,25% (eftir 2,0 "
            "prósentustiga lækkun frá 9,25%) á meðan innlánsvextir ESB voru um 2,75%."
        ),
    )


def fix_poll_data_014(conn):
    """Fix sample size from 9,958 to 1,898 and participation rate."""
    print("\n--- POLL-DATA-014: Sample size 9,958 → 1,898 ---")
    update_entry(
        conn,
        "POLL-DATA-014",
        statement=(
            "The Gallup Þjóðarpúls survey conducted February–March 2026 (sample size "
            "approximately 1,898, response rate 42.7%, yielding approximately 810 "
            "completed responses) showed 42% of Icelanders support EU membership and "
            "42% oppose it, with approximately 16% undecided. A separate question about "
            "the referendum process showed 57% support for holding a referendum on "
            "whether to open accession negotiations, approximately 30% opposed, and "
            "~13% undecided."
        ),
        statement_is=(
            "Þjóðarpúls Gallup (febrúar–mars 2026, n≈1.898, svarhlutfall 42,7%, "
            "um 810 fullkláruð svör) sýndi 42% Íslendinga hlynnt ESB-aðild og 42% "
            "á móti, með um 16% óákveðna. Sérstök spurning um þjóðaratkvæðagreiðslu "
            "sýndi 57% stuðning við að halda hana."
        ),
    )


def fix_housing_data_008(conn):
    """Fix: 7.5–8.5% labelled as indexed → these are non-indexed rates."""
    print("\n--- HOUSING-DATA-008: indexed rate label → non-indexed ---")
    update_entry(
        conn,
        "HOUSING-DATA-008",
        statement=(
            "There is a significant structural difference between mortgage interest rates "
            "in Iceland and the euro area. The European Central Bank's MFI interest rate "
            "statistics show that the average interest rate on new housing loans in the "
            "euro area ranged from approximately 3.2% to 3.8% in late 2025/early 2026, "
            "depending on the fixation period and member state. In contrast, Seðlabanki "
            "Íslands data shows average interest rates on new non-indexed variable-rate "
            "housing loans (óverðtryggð lán) in Iceland at approximately 7.5–8.5%, while "
            "indexed mortgages (verðtryggð lán) carry a nominal rate of 3.5–5.5% plus CPI "
            "adjustment. The comparison is structurally complex: Icelandic indexed mortgages "
            "adjust the principal for inflation, meaning the effective real interest rate is "
            "lower than the nominal rate. Euro area mortgages are predominantly nominal (not "
            "inflation-indexed). The appropriate comparison is between total cost of borrowing "
            "over the loan lifetime, not between nominal figures from structurally different "
            "systems."
        ),
        statement_is=(
            "Mikill skipulagsmunur er á húsnæðislánum á Íslandi og á evrusvæðinu. "
            "Óverðtryggð lán á Íslandi bera 7,5–8,5% nafnvexti en verðtryggð lán "
            "bera 3,5–5,5% nafnvexti auk verðbótaþáttar. Meðalvextir á nýjum "
            "húsnæðislánum á evrusvæðinu voru 3,2–3,8%. Samanburður á nafnvöxtum "
            "er villandi þar sem um 80% íslenskra húsnæðislána eru verðtryggð og "
            "höfuðstóll þeirra hækkar með verðbólgu."
        ),
    )


def fix_agri_data_002(conn):
    """Clarify dairy tariffs — up to 80% ad valorem, >100% effective."""
    print("\n--- AGRI-DATA-002: Dairy tariff clarification ---")
    update_entry(
        conn,
        "AGRI-DATA-002",
        statement=(
            "Iceland applies high import tariffs on many agricultural products: up to 80% "
            "ad valorem on dairy products (effective tariff-rate equivalents can exceed 100% "
            "when specific duties per kg are included), 55% on meat, and 30–55% on various "
            "processed foods. These tariffs protect domestic agriculture but contribute to "
            "higher consumer prices. Under EU membership, these tariffs would be replaced by "
            "the EU's Common External Tariff and internal free trade, significantly "
            "restructuring the sector."
        ),
        statement_is=(
            "Ísland leggur háa innflutningstolla á margar landbúnaðarafurðir: allt að 80% "
            "verðtoll á mjólkurvörur (raunverulegt tollígildi getur farið yfir 100% þegar "
            "kilógrammatollur er reiknaður inn), 55% á kjöt og 30–55% á ýmsan unninn mat. "
            "Tollarnir vernda innlendan landbúnað en stuðla að hærra matvælaverði. Með "
            "ESB-aðild myndu þessir tollar víkja fyrir sameiginlegum ytri tollum ESB og "
            "innri fríverslun."
        ),
    )


def fix_agri_data_021(conn):
    """Fix Finland Article 142 aid: ~€560M → ~€290M actual, ~€575M ceiling."""
    print("\n--- AGRI-DATA-021: Finland aid €560M → €290M actual ---")
    # Read current full statement to preserve structure
    update_entry(
        conn,
        "AGRI-DATA-021",
        statement=(
            "Article 142 of the EU's CAP regulation (originally Article 141/142 of the "
            "1994 Act of Accession) allows Finland and Sweden to provide long-term national "
            "aid to farmers in northern regions (above the 62nd parallel). Finland's actual "
            "annual spending under Article 142 is approximately €290 million per year "
            "(authorised ceiling ~€575 million per year per Commission Decision (EU) "
            "2022/2460, roughly 90% of its total national agricultural aid). This represents "
            "a permanent derogation from normal EU state aid rules. The precedent is "
            "potentially significant for Iceland's accession negotiations, as Iceland could "
            "argue for a similar permanent aid framework for its agriculture sector, which "
            "faces comparable climate and geographic challenges to northern Finland."
        ),
        statement_is=(
            "Grein 142 í aðildarsáttmála Finnlands og Svíþjóðar (1994) heimilar þessum "
            "ríkjum langtíma ríkisstuðning við norðlægan landbúnað. Raunútgjöld Finnlands "
            "samkvæmt 142. grein eru um 290 milljónir evra á ári (heimilað hámark ~575 "
            "milljónir evra samkvæmt ákvörðun framkvæmdastjórnarinnar (ESB) 2022/2460). "
            "Þetta fordæmi gæti skipt máli í aðildarviðræðum Íslands þar sem íslenskur "
            "landbúnaður stendur frammi fyrir svipuðum veðurfars- og landfræðilegum "
            "áskorunum og Norður-Finnland."
        ),
    )


def fix_agri_data_018(conn):
    """Fix: 4 unopened chapters → 8 unopened chapters."""
    print("\n--- AGRI-DATA-018: 4 unopened chapters → 8 ---")
    update_entry(
        conn,
        "AGRI-DATA-018",
        statement=(
            "During Iceland's EU accession negotiations (2010–2013), the agriculture "
            "chapter (Chapter 11) was one of the most politically sensitive negotiating "
            "chapters and was never opened for negotiations before the process was "
            "suspended in May 2013. Analytical screening of Chapter 11 was completed by "
            "the European Commission in 2011, identifying significant gaps between "
            "Iceland's agricultural policy and the EU acquis. Key issues included: "
            "Iceland's high tariff protection (incompatible with the EU customs union), "
            "the absence of CAP-compatible direct payment schemes, differences in food "
            "safety and veterinary standards, and the need to fundamentally restructure "
            "agricultural support. Of the 35 negotiating chapters, Iceland opened 27 and "
            "provisionally closed 11. However, 8 chapters were never opened, including "
            "the most politically difficult: Chapter 11 (agriculture), Chapter 12 (food "
            "safety, veterinary and phytosanitary policy), Chapter 13 (fisheries), "
            "Chapter 14 (transport policy), Chapter 17 (economic and monetary policy), "
            "Chapter 22 (regional policy), Chapter 27 (environment), and Chapter 33 "
            "(financial and budgetary provisions). These same chapters would be the "
            "focus of any resumed negotiations."
        ),
        statement_is=(
            "Landbúnaðarkaflinn (11. kafli) var aldrei opnaður í aðildarviðræðum Íslands "
            "og ESB (2010–2013). Af 35 samningsköflum opnaði Ísland 27 og lokaði 11 til "
            "bráðabirgða. Átta kaflar voru aldrei opnaðir, þar á meðal þeir pólitískt "
            "viðkvæmustu: landbúnaður (11), matvælaöryggi (12), sjávarútvegur (13), "
            "samgöngustefna (14), efnahags- og peningamálastefna (17), svæðisstefna (22), "
            "umhverfismál (27) og fjármála- og fjárlagaákvæði (33)."
        ),
    )


def fix_fish_data_019(conn):
    """Fix all inflated catch figures (Eurostat unit error ~10x)."""
    print("\n--- FISH-DATA-019: All catch figures corrected (Eurostat 10x error) ---")
    update_entry(
        conn,
        "FISH-DATA-019",
        statement=(
            "Iceland is one of Europe's largest fishing nations despite its small "
            "population. In 2023, Iceland's total fisheries catch was approximately "
            "1.0–1.2 million tonnes, compared to Norway's approximately 2.5 million "
            "tonnes, Denmark's approximately 700,000 tonnes, and the EU-27's combined "
            "catch of approximately 4–5 million tonnes. On a per capita basis, Iceland's "
            "catch of roughly 2,800 kg per person dwarfs all comparators: Norway at "
            "approximately 460 kg/person, Denmark at approximately 119 kg/person, and "
            "the EU-27 average at well under 20 kg/person."
        ),
        caveats=(
            "Fisheries catch data varies by source and methodology. The original Eurostat "
            "extraction (fish_ca_main) contained figures approximately 10× higher than "
            "verified national statistics for several countries, likely due to a unit or "
            "filter error in the data extraction. The corrected figures here are cross-"
            "referenced against Statistics Iceland (Hagstofa), Norwegian Directorate of "
            "Fisheries, and Danish Ministry of Food data. Per capita figures use "
            "approximate 2023 populations (IS: 380k, NO: 5.4M, DK: 5.9M)."
        ),
        statement_is=(
            "Ísland er ein stærsta sjávarútvegsþjóð Evrópu þrátt fyrir fámennið. "
            "Heildarafli Íslands var um 1,0–1,2 milljónir tonna árið 2023, samanborið "
            "við um 2,5 milljónir tonna hjá Noregi og 700 þúsund tonna hjá Danmörku. "
            "Afli á mann var um 2.800 kg, langt umfram öll samanburðarlönd: Noregur "
            "~460 kg/mann og Danmörk ~119 kg/mann."
        ),
        caveats_is=(
            "Upprunaleg gögn úr Eurostat (fish_ca_main) innihéldu tölur um 10× hærri "
            "en staðfest opinber gögn fyrir nokkur lönd, líklega vegna einingavillu í "
            "gagnaúrvinnslu. Leiðréttar tölur hér eru krossbornar við Hagstofu, norska "
            "sjávarútvegsstofnunina og danska matvælaráðuneytið."
        ),
        confidence="medium",
    )


def fix_fish_data_020(conn):
    """Fix Sweden/Finland catch figures (Eurostat 10x error)."""
    print("\n--- FISH-DATA-020: Sweden/Finland catch figures corrected ---")
    update_entry(
        conn,
        "FISH-DATA-020",
        statement=(
            "Iceland's fisheries catch has remained broadly stable over the 2020–2023 "
            "period, ranging from approximately 1.0 to 1.2 million tonnes annually. "
            "By contrast, the EU-27's combined catch was approximately 4–5 million tonnes "
            "annually, though reporting completeness varies by year. Among the smaller "
            "Nordic EU members, Sweden's annual catch is approximately 160,000–200,000 "
            "tonnes and Finland's approximately 130,000–160,000 tonnes."
        ),
        caveats=(
            "The original Eurostat extraction (fish_ca_main) contained figures "
            "approximately 10× higher than actual catches for Sweden and Finland, "
            "likely due to the same unit/filter error affecting FISH-DATA-019. "
            "Corrected figures are based on national fisheries statistics. "
            "Fisheries data is subject to significant revision. Species-level data "
            "would provide more meaningful comparisons than raw tonnage."
        ),
        statement_is=(
            "Sjávarafli Íslands hefur verið tiltölulega stöðugur á árunum 2020–2023, "
            "um 1,0–1,2 milljónir tonna á ári. Afli Svíþjóðar er um 160–200 þúsund "
            "tonna og Finnlands um 130–160 þúsund tonna á ári."
        ),
        caveats_is=(
            "Upprunaleg gögn úr Eurostat innihéldu tölur um 10× hærri en raunverulegan "
            "afla Svíþjóðar og Finnlands vegna sömu einingavillu og í FISH-DATA-019. "
            "Leiðréttar tölur byggjast á opinberum sjávarútvegsgögnum viðkomandi landa."
        ),
        confidence="medium",
    )


def fix_sov_legal_012(conn):
    """Fix: 'binding' referendum → 'advisory'."""
    print("\n--- SOV-LEGAL-012: binding → advisory referendum ---")
    update_entry(
        conn,
        "SOV-LEGAL-012",
        statement=(
            "EU accession would require constitutional change in Iceland. Article 2 of "
            "the Icelandic Constitution (Stjórnarskrá) vests legislative power jointly "
            "in the Althingi and the President, and Article 21 provides that the President "
            "can refuse to sign legislation. There is no explicit provision for transferring "
            "sovereignty to international organisations. Legal scholars are divided on "
            "whether accession would require a constitutional amendment — some argue that "
            "a simple act of parliament ratifying the accession treaty would suffice, while "
            "others insist that the transfer of legislative competence to EU institutions "
            "requires amending Article 2. The referendum is advisory (ráðgefandi), as "
            "the Icelandic constitution does not provide for binding referenda on policy "
            "questions — Article 26 covers only presidential referral of legislation."
        ),
        statement_is=(
            "ESB-aðild myndi krefjast stjórnarskrárbreytinga á Íslandi þar sem núverandi "
            "stjórnarskrá hefur ekkert ákvæði um framsal valds til alþjóðastofnana. "
            "Lögfræðingar eru ósammála um hvort þetta sé nauðsynlegt. Þjóðaratkvæðagreiðslan "
            "er ráðgefandi þar sem íslensk stjórnarskrá gerir ekki ráð fyrir bindandi "
            "þjóðaratkvæðagreiðslum um stefnumál — 26. grein tekur einungis til "
            "synjunarvalds forseta."
        ),
    )


def fix_sov_legal_007(conn):
    """Fix cooling-off period: 18 months → 2 years (3 for President)."""
    print("\n--- SOV-LEGAL-007: cooling-off 18m → 2yr/3yr ---")
    # This entry is about the Independence Party's bill. The comparison to EU is the issue.
    update_entry(
        conn,
        "SOV-LEGAL-007",
        statement=(
            "Sjálfstæðisflokkurinn (Independence Party) introduced a bill in Althingi "
            "proposing an 18-month cooling-off period that would prevent senior officials "
            "and ministerial advisors involved in negotiations from taking positions with "
            "international organisations for 18 months after leaving office. The bill "
            "mirrors but is shorter than the EU's own revolving-door rules, which impose "
            "a 2-year cooling-off period on departing Commissioners (extended to 3 years "
            "for the Commission President), as set out in the Code of Conduct C(2018) 700 "
            "and Article 245 TFEU."
        ),
        statement_is=(
            "Sjálfstæðisflokkurinn lagði fram frumvarp á Alþingi um 18 mánaða biðtíma "
            "sem myndi banna háttsettum embættismönnum að þiggja stöður hjá "
            "alþjóðastofnunum eftir að þeir láta af embætti. Þetta er styttra en reglur "
            "ESB sjálfs, sem kveða á um 2 ára biðtíma fyrir fráfarandi framkvæmdastjóra "
            "(3 ár fyrir forseta framkvæmdastjórnarinnar) samkvæmt siðareglum C(2018) 700."
        ),
    )


def fix_eea_data_011(conn):
    """Fix: Art 102 never invoked → Iceland hasn't, Norway has."""
    print("\n--- EEA-DATA-011: Art 102 — Iceland never, Norway has ---")
    update_entry(
        conn,
        "EEA-DATA-011",
        statement=(
            "Iceland's participation in the EU single market through the EEA Agreement "
            "creates a significant democratic deficit. As of 2025, the EEA Agreement has "
            "incorporated approximately 13,000 EU legal acts into Icelandic law. These "
            "acts were adopted by the EU Council and European Parliament — institutions "
            "in which Iceland has no representation. The EEA Joint Committee incorporates "
            "approximately 300–500 new EU acts per year. While the EEA EFTA states have "
            "a formal 'decision-shaping' role, they have no 'decision-making' power. "
            "Iceland has never exercised its Article 102 'right of reservation' to veto "
            "any of the ~13,000 incorporated acts. Norway, by contrast, has invoked "
            "Article 102 reservations on several occasions (including the Third Postal "
            "Directive and the AIFM Directive), though most were eventually resolved. "
            "Full EU membership would replace this 'legislation without representation' "
            "with formal voting rights: a Council vote, 6+ European Parliament seats, "
            "and a European Commissioner."
        ),
        caveats=(
            "The democratic deficit argument is sometimes overstated. The EEA excludes "
            "major policy areas (agriculture, fisheries, customs, tax, foreign and "
            "security policy, justice and home affairs) where Iceland retains full "
            "sovereignty. If Iceland joined the EU, it would gain voting rights but also "
            "extend EU law to these currently excluded areas. Small member states' voting "
            "weight is modest — Malta's influence in Council is limited. The decision-"
            "shaping tools, while weak, are not zero: Iceland's experts participate in "
            "hundreds of EU working groups. Norway's use of Article 102 shows the "
            "reservation right is legally available, even if Iceland has chosen not to "
            "use it."
        ),
        statement_is=(
            "EES-samningurinn skapar verulegan lýðræðishalla þar sem Ísland hefur innleitt "
            "um 13.000 lagagerðir ESB án atkvæðisréttar. Ísland hefur aldrei beitt "
            "neitunarvaldi sínu samkvæmt 102. grein, en Noregur hefur gert það nokkrum "
            "sinnum (m.a. varðandi þriðju póstþjónustutilskipunina og AIFM-tilskipunina). "
            "Full ESB-aðild myndi veita atkvæðisrétt í ráðherraráði, 6+ þingsæti í "
            "Evrópuþinginu og framkvæmdastjóra."
        ),
        caveats_is=(
            "Rökin um lýðræðishalla eru stundum ofmetin. EES-samningurinn útilokar stóra "
            "málaflokka þar sem Ísland heldur fullu fullveldi. Ef Ísland gengi í ESB "
            "fengi það atkvæðisrétt en lög ESB næðu þá einnig yfir undanskildu "
            "málaflokka. Notkun Noregs á 102. grein sýnir að neitunarvaldið er til "
            "staðar, jafnvel þótt Ísland hafi kosið að nýta það ekki."
        ),
    )


def fix_eea_data_007(conn):
    """Fix: 200 untransposed directives → 12–17 directives."""
    print("\n--- EEA-DATA-007: 200 directives → 12–17 ---")
    update_entry(
        conn,
        "EEA-DATA-007",
        statement=(
            "Iceland's compliance with transposing EEA-relevant EU legislation has been "
            "imperfect. The EFTA Surveillance Authority (ESA) Internal Market Scoreboard "
            "reported an incorporation deficit of 2.1% (approximately 17 directives) in "
            "January 2025, improving to 1.4% (approximately 12 directives) by July 2025. "
            "The broader EEA Joint Committee incorporation backlog — covering all legal "
            "acts, not just directives — stood at approximately 400–500 outstanding acts. "
            "ESA opened 25–35 formal infringement cases per year against Iceland in "
            "2020–2024, comparable to medium-performing EU member states."
        ),
        caveats=(
            "Incorporation deficit metrics measure timeliness, not substantive compliance. "
            "The directive transposition deficit (12–17 directives out of ~800) should "
            "not be confused with the broader incorporation backlog of all legal acts "
            "(400–500). Some delays reflect Iceland's small civil service capacity rather "
            "than political resistance. EU member states also have significant "
            "transposition deficits — Iceland's record is comparable to or better than "
            "several EU members."
        ),
        statement_is=(
            "Innleiðing Íslands á EES-löggjöf hefur ekki verið gallalaus. Samkvæmt ESA "
            "innri markaðsskýrslu var innleiðingarhalli tilskipana 2,1% (um 17 tilskipanir) "
            "í janúar 2025 og batnaði í 1,4% (um 12 tilskipanir) í júlí 2025. Breiðari "
            "innleiðingareftirstandinn — allar lagagerðir, ekki aðeins tilskipanir — var "
            "400–500 gerðir. ESA opnaði 25–35 brotamál á ári gegn Íslandi á árunum 2020–2024."
        ),
        caveats_is=(
            "Innleiðingarhalli mælir tímanleika, ekki efnislega fylgni. Tilskipunareftirstand "
            "(12–17 tilskipanir af ~800) má ekki rugla saman við breiðari innleiðingareftirstand "
            "allra lagagerða (400–500). Sumar tafir endurspegla smæð stjórnsýslunnar fremur "
            "en pólitíska andstöðu."
        ),
        confidence="high",
    )


def fix_political_data_012(conn):
    """Fix wrong leader name — Þórdís Kolbrún → Þorgerður Katrín."""
    print("\n--- POLITICAL-DATA-012: Wrong leader name fix ---")
    # The IS version already has the right name, but EN version is wrong
    update_entry(
        conn,
        "POLITICAL-DATA-012",
        statement=(
            "Þorgerður Katrín Gunnarsdóttir, leader of Viðreisn (Reform Party), serves "
            "as utanríkisráðherra (Foreign Minister) in the coalition government formed "
            "in late 2024. She has been Viðreisn's leader since 2018 and an Althingi MP "
            "since 2016. As Foreign Minister, she oversees the EU referendum process and "
            "has been the government's primary spokesperson on the question. She announced "
            "the referendum date of 29 August 2026."
        ),
        statement_is=(
            "Þorgerður Katrín Gunnarsdóttir, formaður Viðreisnar og utanríkisráðherra, "
            "hefur verið aðaltalsmaður ríkisstjórnarinnar um þjóðaratkvæðagreiðsluna og "
            "leiðir ESB-ferlið. Hún tilkynnti dagsetninguna 29. ágúst 2026."
        ),
    )


def fix_pol_data_011(conn):
    """Fix outdated seat counts → session 157 data."""
    print("\n--- POL-DATA-011: Seat counts → session 157 ---")
    update_entry(
        conn,
        "POL-DATA-011",
        statement=(
            "The EU question cuts across traditional party lines in the Althingi. Based "
            "on session 157 (following the 2024 elections), an informal cross-party pro-EU "
            "grouping includes all Viðreisn MPs (11), most Samfylkingin MPs (12–13 of 13), "
            "and individual MPs from other parties — totalling approximately 25–30 of 63 MPs "
            "who would personally favour EU membership. The sceptical bloc includes most "
            "Independence Party MPs (majority of 13), most Miðflokkur MPs (8), most Flokkur "
            "fólksins MPs (8), and most Progressive Party MPs (4) — approximately 25–30 MPs. "
            "The remaining MPs are genuinely uncommitted. Píratar lost all seats in the "
            "2024 election. These numbers are estimates based on public statements and "
            "voting patterns rather than a formal count."
        ),
        caveats=(
            "MP-level counts are approximate and based on public statements, which may not "
            "reflect private views. The Althingi's composition may change before the "
            "referendum due to party switches or by-elections. Session 157 seat counts: "
            "Independence Party 13, Samfylkingin 13, Viðreisn 11, Miðflokkur 8, Flokkur "
            "fólksins 8, Progressive Party 4, other/independent 6."
        ),
        statement_is=(
            "ESB-spurningin þverar hefðbundnar flokkslínur á Alþingi. Á 157. löggjafarþingi "
            "(eftir kosningar 2024) eru um 25–30 þingmenn persónulega hlynntir ESB-aðild "
            "(allir úr Viðreisn (11), flestir úr Samfylkingunni (12–13 af 13) og einstaklingar "
            "úr öðrum flokkum) og 25–30 andvígir. Píratar misstu öll þingsæti í kosningunum "
            "2024."
        ),
        caveats_is=(
            "Fjöldi þingmanna er áætlaður og byggður á opinberum yfirlýsingum. "
            "Sætafjöldi á 157. þingi: Sjálfstæðisflokkur 13, Samfylkingin 13, "
            "Viðreisn 11, Miðflokkur 8, Flokkur fólksins 8, Framsóknarflokkur 4."
        ),
    )


def fix_pol_data_001(conn):
    """Fix seat count: 17 → 24."""
    print("\n--- POL-DATA-001: Combined seats 17 → 24 ---")
    update_entry(
        conn,
        "POL-DATA-001",
        statement=(
            "Samfylkingin (Social Democrats) and Viðreisn (Reform Party) are the two "
            "Althingi parties that formally support EU membership. Samfylkingin has "
            "supported EU membership since 2007 and led the 2009 application process "
            "while in government. Viðreisn was founded in 2016 partly on a pro-EU "
            "platform and has consistently advocated for completing accession "
            "negotiations. Together they hold 24 of 63 Althingi seats after the 2024 "
            "elections (Samfylkingin 13, Viðreisn 11)."
        ),
        statement_is=(
            "Samfylkingin og Viðreisn eru einu þingflokkar Alþingis sem styðja formlega "
            "ESB-aðild. Samfylkingin hefur stutt aðild síðan 2007 og leiddi umsóknarferlið "
            "2009, en Viðreisn var stofnuð 2016 meðal annars á ESB-vettvangi. Saman halda "
            "þau 24 af 63 þingsætum eftir kosningar 2024 (Samfylkingin 13, Viðreisn 11)."
        ),
    )


def fix_prec_hist_004(conn):
    """Fix: 11 opened, none closed → 27 opened, 11 closed."""
    print("\n--- PREC-HIST-004: 11 opened → 27 opened, 11 closed ---")
    update_entry(
        conn,
        "PREC-HIST-004",
        statement=(
            "Iceland opened EU accession negotiations in July 2010 under the Social "
            "Democrat-led government. Of 33 negotiation chapters, 27 were opened and "
            "11 were provisionally closed — an unprecedented pace enabled by existing "
            "EEA compliance. The most contentious chapter (13: Fisheries) was among the "
            "8 chapters never opened. The centre-right government elected in 2013 froze "
            "negotiations, and Iceland formally withdrew its application in March 2015."
        ),
        statement_is=(
            "Ísland hóf aðildarviðræður við ESB í júlí 2010 undir forystu "
            "Samfylkingarinnar. Af 33 samningsköflum voru 27 opnaðir og 11 lokaðir "
            "til bráðabirgða — óvenjuhraður framgangur vegna EES-aðlögunar. Kafli 13 "
            "um sjávarútveg var meðal 8 kafla sem aldrei voru opnaðir. Miðjuhægri "
            "ríkisstjórnin sem tók við 2013 frysti viðræðurnar og Ísland dró umsókn "
            "sína til baka í mars 2015."
        ),
    )


def main():
    conn = connect()

    try:
        fix_curr_data_003(conn)
        fix_curr_data_004(conn)
        fix_currency_data_015(conn)
        fix_poll_data_014(conn)
        fix_housing_data_008(conn)
        fix_agri_data_002(conn)
        fix_agri_data_021(conn)
        fix_agri_data_018(conn)
        fix_fish_data_019(conn)
        fix_fish_data_020(conn)
        fix_sov_legal_012(conn)
        fix_sov_legal_007(conn)
        fix_eea_data_011(conn)
        fix_eea_data_007(conn)
        fix_political_data_012(conn)
        fix_pol_data_011(conn)
        fix_pol_data_001(conn)
        fix_prec_hist_004(conn)

        conn.commit()
        print(f"\n=== COMMITTED {len(CHANGED_IDS)} updates ===")
        print("Changed IDs:", CHANGED_IDS)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
