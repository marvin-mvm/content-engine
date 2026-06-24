# Acme Labs — Product Catalog (reference)

> **On-demand reference. Not auto-injected.** Read this file when you need product
> facts for a post, caption, image spec, or product page — compound class, format,
> spec line, price, or SKU.
>
> **Source of truth = the live store `acmelabs.co/shop`.** This file is SYNCED from the
> site's product bundle (`/assets/index-*.js`) — last sync **2026-06-23**. If it disagrees
> with the live site, the SITE wins; re-pull the bundle and update this file. The engine's
> `research.py COMPOUND_CATALOG` + `engine_state.topic_weights` are synced to the same source.
>
> Compliance is non-negotiable (see SOUL.md): research framing only, never
> "treats/cures/prevents", never personal-use or weight-loss claims, never dosing
> as medical advice. Research-use-only materials, not for human consumption.

---

## Standard framing for EVERY product page / image

- **Badge:** `RUO · NOT FOR HUMAN CONSUMPTION`
- **Trust chip:** `COA Available — US 3rd-party verified, batch-traceable`
- **Storage:** Lyophilized, shipped cold-chain worldwide
- **Link / COA:** `https://acmelabs.co/shop/<slug>` (the SKU below is the exact slug)

---

## Live individual research compounds (22 SKUs, sold now)

### Metabolic
| Compound | SKU `/shop/` | Price | Spec | Class |
|---|---|---|---|---|
| Semaglutide | `semaglutide` | $79 | 5mg lyophilized | GLP-1 Analog |
| Tirzepatide | `tirzepatide` | $99 | 10mg lyophilized | GIP / GLP-1 Analog |
| Retatrutide | `retatrutide` | $99 | 10mg lyophilized | GGG Tri-Agonist (GIP/GLP-1/glucagon) |
| Cagrilintide | `cagrilintide-5mg` | $89 | 5mg lyophilized | Amylin Analog |
| Cagri/Sema Blend | `cagri-sema-5mg` | $99 | 5mg lyophilized | Metabolic Blend |

### Recovery / Repair
| Compound | SKU `/shop/` | Price | Spec | Class |
|---|---|---|---|---|
| BPC-157 | `bpc-157` | $49 | 5mg lyophilized (10mg variant on-site) | Pentadecapeptide |
| TB-500 | `tb-500-10mg` | $69 | 10mg lyophilized | Thymosin β-4 fragment |
| GHK-Cu | `ghk-cu-50mg` | $49 | 50mg lyophilized | Copper Peptide |
| Thymosin Alpha-1 (TA-1) | `ta-1-10mg` | $65 | 10mg lyophilized | Immune Peptide |
| BPC-157 / TB-500 Blend | `bpc-tb500-blend` | $79 | 5/5mg lyophilized | Recovery Blend |

### Growth / GH-axis
| Compound | SKU `/shop/` | Price | Spec | Class |
|---|---|---|---|---|
| CJC-1295 (No DAC) | `cjc-1295-no-dac-10mg` | $59 | 10mg lyophilized | GHRH |
| CJC-1295 (with DAC) | `cjc-1295-dac-5mg` | $75 | 5mg lyophilized | GHRH |
| CJC-1295 / Ipamorelin Blend | `cjc-1295-ipamorelin` | $65 | 5/5mg lyophilized | GHRH / GHRP Blend |
| Ipamorelin | `ipamorelin` | $49 | 5mg lyophilized | GHRP |
| Tesamorelin | `tesamorelin-10mg` | $65 | 10mg lyophilized | GHRH |
| IGF-1 LR3 | `igf1-lr3-1mg` | $79 | 1mg lyophilized | Growth Factor |
| MOTS-c | `mots-c` | $55 | 10mg lyophilized | Mitochondrial Peptide |

### Cognitive
| Compound | SKU `/shop/` | Price | Spec | Class |
|---|---|---|---|---|
| Semax | `semax` | $75 | 30mg nasal | Heptapeptide (neuropeptide) |
| Selank | `selank-5mg` | $49 | 5mg lyophilized | Heptapeptide (neuropeptide) |

### Longevity
| Compound | SKU `/shop/` | Price | Spec | Class |
|---|---|---|---|---|
| NAD+ | `nad-injection` | $65 | 500mg vial | Coenzyme |

### Aesthetic / Melanocortin — *static / carousel / announcement only, NOT video/reels*
| Compound | SKU `/shop/` | Price | Spec | Class |
|---|---|---|---|---|
| Melanotan-2 | `melanotan-2-10mg` | $49 | 10mg lyophilized | Melanocortin |
| PT-141 (Bremelanotide) | `pt-141-10mg` | $49 | 10mg lyophilized | Melanocortin |

---

## Bundles & Stacks (9 SKUs)

| Stack | SKU `/shop/` | Price | Contains |
|---|---|---|---|
| GLP Bundle | `glp-bundle` | $129 | Metabolic stack |
| Gains Bundle | `gains-bundle` | $139 | CJC/IPA + BPC-157 5mg + Ipamorelin 5mg |
| Recovery Pro | `recovery-pro` | $179 | BPC-157 10mg + TB-500 10mg + IGF-1 |
| Repair Starter | `repair-starter` | $99 | BPC-157 5mg + TB-500 10mg |
| Longevity Stack | `longevity-stack` | $149 | NAD+ + MOTS-c + GHK-Cu |
| Cognitive Bundle | `cognitive-bundle` | $109 | Semax + Selank |
| Collagen Research Bundle | `collagen-research-bundle` | $89 | GHK-Cu + BPC-157 5mg |
| GLOW | `glow-70mg` | $99 | 70mg aesthetic blend |
| KLOW | `klow-80mg` | $119 | 80mg aesthetic blend |

## Supplies
| Item | SKU `/shop/` | Price |
|---|---|---|
| Bacteriostatic Water | `bacteriostatic-water` | $14 (10 mL diluent) |

---

## What the content engine rotates

`research.py COMPOUND_CATALOG` + `engine_state.topic_weights` rotate **18** of the individual
compounds above (the single-compound SKUs; blends/variants `cagri-sema-5mg`, `bpc-tb500-blend`,
`cjc-1295-dac-5mg`, `cjc-1295-ipamorelin` and the stacks are sold but not separate rotation topics).
**Melanotan-2 and PT-141 are image-only** — excluded from autonomous reel/video topics
(`research.VIDEO_EXCLUDED_COMPOUNDS`) but eligible for static / carousel / announcement cards.

## Not yet live (hidden on-site — do NOT feature / link)

Hidden in the bundle, so no live `/shop/` page: **Epithalon**, **Sermorelin**, **KPV**, plus
protocol/supplement lines — Rapamycin & Metformin protocols, Senolytic protocols, Microdosed GLP-1,
Metabolic Peptide Stack, and the foundational supplements (Multivitamin, Omega-3, D3-K2, Magnesium,
Creatine + B-complex, Lipotropic B12, Electrolyte/Sleep/Cognitive kits, NAD precursor complex, etc.).
