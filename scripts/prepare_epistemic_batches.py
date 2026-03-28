"""Prepare batch context files for subagent epistemic type classification."""

import json
from pathlib import Path

from esbvaktin.ground_truth.operations import get_connection

BATCH_SIZE = 50
OUTDIR = Path("data/backfill")


def main():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, claim_slug, canonical_text_is
        FROM claims
        WHERE epistemic_type = 'factual'
        ORDER BY id
        """
    ).fetchall()
    conn.close()

    # Split into batches
    batches = []
    for i in range(0, len(rows), BATCH_SIZE):
        batches.append(rows[i : i + BATCH_SIZE])

    print(f"{len(rows)} claims in {len(batches)} batches of {BATCH_SIZE}")

    OUTDIR.mkdir(parents=True, exist_ok=True)

    manifest = []

    for batch_idx, batch in enumerate(batches):
        claims_block = ""
        for cid, slug, text in batch:
            claims_block += f"- **ID {cid}** ({slug}): {text}\n"

        context = f"""# Þekkingarfræðileg flokkun — Lota {batch_idx + 1}/{len(batches)}

Þú ert að flokka fullyrðingar eftir þekkingarfræðilegri tegund (epistemic type).

## Flokkar

- **factual**: Bein fullyrðing um heiminn sem hægt er að staðfesta. Þetta er sjálfgefinn flokkur — notaðu hann ef fullyrðingin passar ekki í aðra flokka.
- **hearsay**: Byggt á ónafngreindum eða óstaðfestanlegum heimildum. Leitaðu að: «að sögn», «fregnir herma», «samkvæmt heimildum», «mun hafa sagt», «ónafngreindir viðmælendur». ATHUGIÐ: Ef heimildin er nafngreind og opinber (t.d. ráðherra á Alþingi) er þetta EKKI hearsay — það er factual.
- **counterfactual**: Um FORTÍÐINA — andstætt því sem raunverulega gerðist. Leitaðu að: «ef X hefði», «hefði í för með sér», «hefði getað/mátt». Þetta er EINUNGIS um fortíðina.
- **prediction**: Um FRAMTÍÐINA, þ.m.t. skilyrtar spár. Leitaðu að: «myndi», «mundi», «mun verða», «ef aðild næðist», «ef Ísland gengur í», «kæmi til með að», «stefnir í». Athugið: «ESB-aðild myndi leiða til...» er prediction. «ESB-reglur kveða á um...» er factual (lýsir núverandi reglum).

## Mikilvægar aðgreiningar

1. Fullyrðing um NÚVERANDI reglur ESB er **factual**, jafnvel þótt Ísland sé ekki aðili. «Sameiginleg sjávarútvegsstefna ESB gildir um alla aðildarríki» = factual (lýsir gildandi reglum).
2. Fullyrðing um hvað MYNDI gerast ef Ísland gengi í = **prediction**.
3. Fullyrðing um hvað HEFÐI gerst ef Ísland hefði gengið í = **counterfactual**.
4. Nafngreind heimild = **factual**. Ónafngreind heimild = **hearsay**.

## Fullyrðingar til flokkunar

{claims_block}

## Úttakssnið

Skrifaðu JSON-fylki. Sýndu EINUNGIS fullyrðingar sem ÆTT AÐ BREYTA — slepptu þeim sem eru réttilega «factual»:

```json
[
  {{"id": 123, "epistemic_type": "prediction"}},
  {{"id": 456, "epistemic_type": "hearsay"}}
]
```

Ef ENGIN fullyrðing í þessari lotu þarf að breytast, skrifaðu tómt fylki: `[]`
"""

        filepath = OUTDIR / f"_context_batch_{batch_idx + 1}.md"
        filepath.write_text(context, encoding="utf-8")
        manifest.append(
            {
                "batch": batch_idx + 1,
                "file": str(filepath),
                "claim_ids": [r[0] for r in batch],
                "count": len(batch),
            }
        )

    # Write manifest
    (OUTDIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(batches)} context files to {OUTDIR}/")


if __name__ == "__main__":
    main()
