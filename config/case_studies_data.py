"""Static case study content for the public marketing pages.

No CaseStudy model exists in the project, so case studies are defined here as a
list of dicts. The same data drives both the listing page (card_* fields) and
the detail page (headline / hero_stats / sections).

Detail ``sections`` is an ordered list of typed blocks rendered by
templates/case-study-details.html:

  {"type": "text",    "heading": str, "paragraphs": [str, ...], "bullets": [str, ...]}
  {"type": "quote",   "text": str, "author": str, "title": str, "alt": bool}
  {"type": "results", "heading": str, "cards": [{"number": str, "label": str}, ...],
                      "paragraphs": [str, ...]}
"""

CASE_STUDIES = [
    {
        "slug": "aladimeji-farms-40-percent-mortality-reduction",
        # --- listing card ---
        "emoji": "🐔 🇳🇬",
        "card_badge": "LAGOS · 25,000 BIRDS",
        "card_title": "Aladimeji Farms: 40% Mortality Reduction",
        "card_stats": ["📉 -40% Mortality", "💰 ₦12M Saved/Year", "⚠️ 72hr Early Warning"],
        "card_excerpt": (
            "\"FlockIQ's anomaly detection alerted us to a respiratory outbreak 3 days "
            "before clinical signs appeared. We isolated the affected house and saved "
            "over 4,000 birds. The AI paid for itself in one cycle.\""
        ),
        # --- detail page ---
        "farm_name": "Aladimeji Farms",
        "description": (
            "How Aladimeji Farms reduced mortality by 40% and saved ₦12M annually using "
            "FlockIQ's AI-powered poultry management platform."
        ),
        "detail_badge": "LAGOS · 25,000 BIRDS · BROILERS",
        "headline": "How Aladimeji Farms Reduced Mortality by 40% and Saved ₦12M Annually",
        "hero_stats": [
            {"value": "-40%", "label": "Mortality Reduction"},
            {"value": "₦12M", "label": "Annual Savings"},
            {"value": "72hr", "label": "Early Warning"},
        ],
        "sections": [
            {
                "type": "text",
                "heading": "Executive Summary",
                "paragraphs": [
                    "Aladimeji Farms, a 25,000-bird broiler operation in Lagos, was struggling "
                    "with recurring respiratory outbreaks that claimed 12-15% of each flock. "
                    "Traditional monitoring methods meant outbreaks were only detected after "
                    "birds showed clinical signs — often too late to prevent significant losses.",
                    "After implementing FlockIQ's AI-powered anomaly detection system, the farm "
                    "now receives alerts 72 hours before symptoms appear, enabling early "
                    "intervention. Within three cycles, mortality dropped from 12% to 7.2% — a "
                    "40% reduction — saving the farm over ₦12 million annually.",
                ],
            },
            {
                "type": "text",
                "heading": "The Challenge",
                "paragraphs": [
                    "Before FlockIQ, Aladimeji Farms relied on manual daily checks and visual "
                    "inspection. By the time a sick bird was spotted, the disease had often "
                    "spread to entire houses. Key challenges included:",
                ],
                "bullets": [
                    "15-20% mortality during respiratory outbreaks",
                    "No early warning system for disease detection",
                    "Missed vaccination schedules due to manual tracking",
                    "Inconsistent feed and water consumption records",
                ],
            },
            {
                "type": "quote",
                "text": (
                    "Before FlockIQ, we were always reacting to problems after they happened. "
                    "Birds would get sick, and by the time we noticed, we'd already lost "
                    "hundreds. It was heartbreaking and expensive."
                ),
                "author": "Mr. Adeboye Aladimeji",
                "title": "Chairman, Aladimeji Farms",
            },
            {
                "type": "text",
                "heading": "The Solution",
                "paragraphs": ["Aladimeji Farms deployed FlockIQ's full platform, including:"],
                "bullets": [
                    "<strong>AI Anomaly Detection</strong> — Real-time Z-score analysis of "
                    "mortality, water consumption, and feed intake",
                    "<strong>Vaccination Scheduler</strong> — Automated reminders for all "
                    "breed-specific vaccines",
                    "<strong>SMS Alerts</strong> — Critical notifications sent directly to farm "
                    "managers' phones",
                    "<strong>Daily Logging</strong> — Mobile-first data entry for mortality, "
                    "feed, and water",
                ],
            },
            {
                "type": "results",
                "heading": "The Results",
                "cards": [
                    {"number": "-40%", "label": "Mortality Rate"},
                    {"number": "72hr", "label": "Early Warning Before Symptoms"},
                    {"number": "₦12M", "label": "Saved Annually"},
                    {"number": "100%", "label": "Vaccination Compliance"},
                ],
                "paragraphs": [
                    "The AI detected a 15% drop in water consumption and a 0.8% daily mortality "
                    "increase — patterns invisible to the human eye. Three days later, birds in "
                    "the adjacent house showed respiratory symptoms. The farm had already "
                    "isolated the affected area and started treatment.",
                ],
            },
            {
                "type": "quote",
                "alt": True,
                "text": (
                    "FlockIQ gave us a crystal ball. We saw the outbreak coming before any bird "
                    "looked sick. That 72-hour warning saved us over 4,000 birds in that single "
                    "cycle."
                ),
                "author": "Mr. Adeboye Aladimeji",
                "title": "Chairman, Aladimeji Farms",
            },
            {
                "type": "text",
                "heading": "What's Next",
                "paragraphs": [
                    "Encouraged by the results, Aladimeji Farms is expanding its FlockIQ "
                    "deployment to all three farm locations and exploring the financial "
                    "intelligence module to optimize sale timing and improve profit margins.",
                    "\"We're not just reducing losses anymore — we're actively growing. FlockIQ "
                    "has transformed how we manage our birds, and we're targeting a 5% mortality "
                    "rate in the next cycle,\" says Mr. Aladimeji.",
                ],
            },
            {
                "type": "text",
                "heading": "Key Takeaways",
                "bullets": [
                    "AI can detect disease outbreaks 72 hours before clinical symptoms appear",
                    "Early intervention dramatically reduces mortality and financial loss",
                    "Automated vaccination scheduling ensures 100% compliance",
                    "Mobile-first design works even with intermittent internet connectivity",
                ],
            },
        ],
    },
    {
        "slug": "golden-egg-farms-18-percent-egg-increase",
        "emoji": "🥚 📊",
        "card_badge": "IBADAN · 50,000 LAYERS",
        "card_title": "Golden Egg Farms: 18% Egg Production Increase",
        "card_stats": ["🥚 +18% Egg Yield", "📈 95% Peak Production", "💊 Vaccine Compliance: 100%"],
        "card_excerpt": (
            "\"The vaccination scheduler eliminated missed doses. Our layer peak production "
            "hit 95% — the highest in our 15-year history. FlockIQ turned our data into "
            "actionable intelligence.\""
        ),
        "farm_name": "Golden Egg Farms",
        "description": (
            "How Golden Egg Farms in Ibadan lifted egg production by 18% and reached 95% peak "
            "lay using FlockIQ's egg forecasting and vaccination scheduling."
        ),
        "detail_badge": "IBADAN · 50,000 BIRDS · LAYERS",
        "headline": "How Golden Egg Farms Increased Egg Production by 18% and Hit 95% Peak Lay",
        "hero_stats": [
            {"value": "+18%", "label": "Egg Production"},
            {"value": "95%", "label": "Peak Production"},
            {"value": "100%", "label": "Vaccine Compliance"},
        ],
        "sections": [
            {
                "type": "text",
                "heading": "Executive Summary",
                "paragraphs": [
                    "Golden Egg Farms runs 50,000 layers across multiple houses in Ibadan. "
                    "Despite 15 years of experience, the farm could not consistently push peak "
                    "production above 88%, and unexplained dips in lay rate were eroding margins.",
                    "By adopting FlockIQ's egg-production forecasting and automated vaccination "
                    "scheduling, the farm lifted average production by 18% and reached a record "
                    "95% peak lay — the highest in its history.",
                ],
            },
            {
                "type": "text",
                "heading": "The Challenge",
                "paragraphs": [
                    "The team had plenty of records but no way to turn them into decisions. "
                    "Recurring problems included:",
                ],
                "bullets": [
                    "Production dips that were only noticed days after they began",
                    "Occasional missed or late vaccinations across staggered flocks",
                    "No reliable forecast to plan packaging, labour, and sales",
                    "Lighting and feeding adjustments based on guesswork, not data",
                ],
            },
            {
                "type": "quote",
                "text": (
                    "We had fifteen years of notebooks, but we were still surprised every time "
                    "production dropped. We needed something that could see the pattern before "
                    "we did."
                ),
                "author": "Mrs. Folake Adeyemi",
                "title": "Operations Director, Golden Egg Farms",
            },
            {
                "type": "text",
                "heading": "The Solution",
                "paragraphs": ["Golden Egg Farms put FlockIQ at the centre of daily operations:"],
                "bullets": [
                    "<strong>AI Egg Forecasting</strong> — Daily production predictions per "
                    "flock using Prophet-based models",
                    "<strong>Vaccination Scheduler</strong> — Breed- and age-specific reminders "
                    "for every staggered flock",
                    "<strong>Anomaly Detection</strong> — Early flags on lay-rate and feed-intake "
                    "deviations",
                    "<strong>Performance Dashboards</strong> — Hen-day production and feed "
                    "efficiency tracked at a glance",
                ],
            },
            {
                "type": "results",
                "heading": "The Results",
                "cards": [
                    {"number": "+18%", "label": "Egg Production"},
                    {"number": "95%", "label": "Peak Lay Rate"},
                    {"number": "100%", "label": "Vaccination Compliance"},
                    {"number": "-9%", "label": "Feed Cost per Egg"},
                ],
                "paragraphs": [
                    "With reliable forecasts, the farm matched labour and packaging to expected "
                    "output and caught two early production dips before they became costly. The "
                    "vaccination scheduler removed missed doses entirely, stabilising flock "
                    "health through the peak laying window.",
                ],
            },
            {
                "type": "quote",
                "alt": True,
                "text": (
                    "Hitting 95% peak production was something we'd chased for years. FlockIQ "
                    "turned our data into decisions, and the results speak for themselves."
                ),
                "author": "Mrs. Folake Adeyemi",
                "title": "Operations Director, Golden Egg Farms",
            },
            {
                "type": "text",
                "heading": "What's Next",
                "paragraphs": [
                    "Golden Egg Farms is now using FlockIQ's market insights to time egg sales "
                    "around price swings and is piloting the platform with two contract farms in "
                    "its supply network.",
                ],
            },
            {
                "type": "text",
                "heading": "Key Takeaways",
                "bullets": [
                    "Accurate forecasting lets farms plan labour, packaging, and sales with "
                    "confidence",
                    "Automated scheduling removes the human error behind missed vaccinations",
                    "Catching production dips early protects peak-lay revenue",
                    "Even experienced operators gain an edge from data-driven decisions",
                ],
            },
        ],
    },
    {
        "slug": "northern-pride-theft-detection",
        "emoji": "💰 🔒",
        "card_badge": "KANO · 15,000 BROILERS",
        "card_title": "Northern Pride: Theft Detection Saved ₦8M",
        "card_stats": ["🔍 ₦8M Recovered", "📋 Full Audit Trail", "✅ 1.5% Variance Detection"],
        "card_excerpt": (
            "\"FlockIQ flagged a 2% discrepancy between bird counts and feed consumption. "
            "The audit trail revealed organized theft. We recovered losses and implemented "
            "controls. This feature alone justified the subscription.\""
        ),
        "farm_name": "Northern Pride",
        "description": (
            "How Northern Pride in Kano uncovered organized theft and recovered ₦8M using "
            "FlockIQ's theft detection and tamper-proof audit trail."
        ),
        "detail_badge": "KANO · 15,000 BIRDS · BROILERS",
        "headline": "How Northern Pride Uncovered Organized Theft and Recovered ₦8M",
        "hero_stats": [
            {"value": "₦8M", "label": "Losses Recovered"},
            {"value": "1.5%", "label": "Variance Detected"},
            {"value": "100%", "label": "Audit Coverage"},
        ],
        "sections": [
            {
                "type": "text",
                "heading": "Executive Summary",
                "paragraphs": [
                    "Northern Pride, a 15,000-bird broiler farm in Kano, suspected losses but "
                    "could never prove them. Bird counts roughly matched on paper, yet feed kept "
                    "running short and profits never reflected the flock's performance.",
                    "FlockIQ's theft-detection reconciliation flagged a persistent gap between "
                    "feed consumption and recorded bird numbers. The tamper-proof audit trail "
                    "exposed organized theft, helping the farm recover ₦8 million and lock down "
                    "its processes.",
                ],
            },
            {
                "type": "text",
                "heading": "The Challenge",
                "paragraphs": [
                    "Shrinkage is notoriously hard to detect on a busy farm. Northern Pride "
                    "faced:",
                ],
                "bullets": [
                    "Feed consumption that never matched the number of birds on record",
                    "No reliable way to tell wastage from theft",
                    "Paper records that could be quietly altered",
                    "No audit trail to support action against staff",
                ],
            },
            {
                "type": "quote",
                "text": (
                    "We knew money was leaking somewhere, but every count looked fine on paper. "
                    "Without proof, there was nothing we could do."
                ),
                "author": "Alhaji Musa Ibrahim",
                "title": "Owner, Northern Pride",
            },
            {
                "type": "text",
                "heading": "The Solution",
                "paragraphs": ["FlockIQ gave the farm visibility it never had before:"],
                "bullets": [
                    "<strong>Theft Detection Reconciliation</strong> — Weekly cross-checks of "
                    "bird counts against feed and water consumption",
                    "<strong>Variance Alerts</strong> — Automatic flags when discrepancies cross "
                    "a 1.5% threshold",
                    "<strong>Tamper-Proof Audit Log</strong> — Immutable record of every count, "
                    "edit, and movement",
                    "<strong>Role-Based Access</strong> — Clear accountability for who logged "
                    "what, and when",
                ],
            },
            {
                "type": "results",
                "heading": "The Results",
                "cards": [
                    {"number": "₦8M", "label": "Losses Recovered"},
                    {"number": "1.5%", "label": "Variance Threshold"},
                    {"number": "100%", "label": "Auditable Records"},
                    {"number": "0", "label": "Repeat Incidents"},
                ],
                "paragraphs": [
                    "Within weeks, the reconciliation flagged a consistent 2% gap between feed "
                    "use and bird numbers. The audit trail traced it to coordinated theft "
                    "during off-peak hours. With evidence in hand, the farm recovered its losses "
                    "and introduced controls that have prevented any repeat.",
                ],
            },
            {
                "type": "quote",
                "alt": True,
                "text": (
                    "The audit trail gave us proof, not suspicion. That single feature paid for "
                    "the subscription many times over."
                ),
                "author": "Alhaji Musa Ibrahim",
                "title": "Owner, Northern Pride",
            },
            {
                "type": "text",
                "heading": "What's Next",
                "paragraphs": [
                    "Northern Pride has rolled FlockIQ's controls out across all of its houses "
                    "and now reviews reconciliation reports as part of its weekly management "
                    "routine.",
                ],
            },
            {
                "type": "text",
                "heading": "Key Takeaways",
                "bullets": [
                    "Cross-checking feed against bird counts reveals losses paper records hide",
                    "A tamper-proof audit trail turns suspicion into actionable evidence",
                    "Clear accountability deters theft before it starts",
                    "Loss prevention can pay for the entire platform on its own",
                ],
            },
        ],
    },
    {
        "slug": "zuma-poultry-heat-stress-prevention",
        "emoji": "🌡️ 📱",
        "card_badge": "ABUJA · 8,000 BIRDS",
        "card_title": "Zuma Poultry: Heat Stress Prevention",
        "card_stats": ["🌡️ -65% Heat-Related Losses", "⚡ Real-time SMS Alerts", "💧 Water Consumption Monitoring"],
        "card_excerpt": (
            "\"During the 2026 heatwave, FlockIQ sent SMS alerts when water consumption "
            "dropped. We activated emergency cooling and lost only 2% of our flock while "
            "neighbors lost 15-20%.\""
        ),
        "farm_name": "Zuma Poultry",
        "description": (
            "How Zuma Poultry in Abuja cut heat-related losses by 65% during the 2026 heatwave "
            "using FlockIQ's real-time SMS alerts and water monitoring."
        ),
        "detail_badge": "ABUJA · 8,000 BIRDS · BROILERS",
        "headline": "How Zuma Poultry Cut Heat-Stress Losses by 65% During the 2026 Heatwave",
        "hero_stats": [
            {"value": "-65%", "label": "Heat-Related Losses"},
            {"value": "2%", "label": "Flock Lost vs 15-20%"},
            {"value": "24/7", "label": "SMS Monitoring"},
        ],
        "sections": [
            {
                "type": "text",
                "heading": "Executive Summary",
                "paragraphs": [
                    "Zuma Poultry, an 8,000-bird farm near Abuja, faced devastating losses every "
                    "dry season as temperatures soared. Heat stress could wipe out 15-20% of a "
                    "flock in a single bad week.",
                    "With FlockIQ monitoring water consumption and sending real-time SMS alerts, "
                    "Zuma responded to the 2026 heatwave within minutes instead of hours — losing "
                    "only 2% of its flock while neighbouring farms lost 15-20%.",
                ],
            },
            {
                "type": "text",
                "heading": "The Challenge",
                "paragraphs": [
                    "Heat stress moves fast, and a few hours can be the difference between a "
                    "healthy flock and heavy losses. Zuma struggled with:",
                ],
                "bullets": [
                    "Sudden temperature spikes during the dry season",
                    "No early signal that birds were under heat stress",
                    "Cooling interventions activated too late to help",
                    "Heavy losses concentrated in just a few extreme days",
                ],
            },
            {
                "type": "quote",
                "text": (
                    "By the time you can see the birds panting, you're already losing them. We "
                    "needed a warning the moment something changed, not hours later."
                ),
                "author": "Engr. Sani Bello",
                "title": "Farm Manager, Zuma Poultry",
            },
            {
                "type": "text",
                "heading": "The Solution",
                "paragraphs": ["FlockIQ turned weather and water data into instant action:"],
                "bullets": [
                    "<strong>Water Consumption Monitoring</strong> — Continuous tracking of "
                    "intake as an early heat-stress signal",
                    "<strong>Weather Alerts</strong> — OpenWeatherMap-driven warnings ahead of "
                    "extreme heat",
                    "<strong>Real-Time SMS</strong> — Termii alerts straight to managers' phones, "
                    "no app required",
                    "<strong>Response Playbook</strong> — Clear cooling steps triggered the "
                    "moment thresholds were crossed",
                ],
            },
            {
                "type": "results",
                "heading": "The Results",
                "cards": [
                    {"number": "-65%", "label": "Heat-Related Losses"},
                    {"number": "2%", "label": "Flock Lost in Heatwave"},
                    {"number": "<10min", "label": "Alert to Response"},
                    {"number": "8,000", "label": "Birds Protected"},
                ],
                "paragraphs": [
                    "During the peak of the 2026 heatwave, FlockIQ flagged a sharp drop in water "
                    "consumption and pushed an SMS alert. The team activated emergency cooling "
                    "and misting within minutes. While neighbouring farms reported 15-20% "
                    "mortality, Zuma lost just 2% of its flock.",
                ],
            },
            {
                "type": "quote",
                "alt": True,
                "text": (
                    "That one SMS saved our season. We were cooling the houses while everyone "
                    "else was still trying to figure out what was wrong."
                ),
                "author": "Engr. Sani Bello",
                "title": "Farm Manager, Zuma Poultry",
            },
            {
                "type": "text",
                "heading": "What's Next",
                "paragraphs": [
                    "Zuma Poultry is investing in automated cooling that can be triggered "
                    "directly from FlockIQ alerts, aiming to keep heat-related losses below 1% "
                    "next season.",
                ],
            },
            {
                "type": "text",
                "heading": "Key Takeaways",
                "bullets": [
                    "Water consumption is an early, reliable signal of heat stress",
                    "SMS alerts reach managers even without smartphones or stable internet",
                    "Minutes matter — fast response turns a disaster into a manageable event",
                    "Weather-driven warnings let farms prepare before extreme heat arrives",
                ],
            },
        ],
    },
    {
        "slug": "greenfield-farms-optimal-sale-timing",
        "emoji": "📉 💡",
        "card_badge": "OGUN · 30,000 BROILERS",
        "card_title": "Greenfield Farms: Optimal Sale Timing",
        "card_stats": ["📊 +22% Profit Margin", "⏱️ 7-Day Optimal Window", "💰 ₦5M Extra Revenue"],
        "card_excerpt": (
            "\"The AI predicted the optimal sale window and gave us 7 days' notice. We sold "
            "at peak market price and increased profit margins by 22% — an extra ₦5 million "
            "per cycle.\""
        ),
        "farm_name": "Greenfield Farms",
        "description": (
            "How Greenfield Farms in Ogun lifted profit margins by 22% and earned ₦5M extra per "
            "cycle using FlockIQ's AI sale-timing recommendations."
        ),
        "detail_badge": "OGUN · 30,000 BIRDS · BROILERS",
        "headline": "How Greenfield Farms Boosted Profit Margins by 22% with Smart Sale Timing",
        "hero_stats": [
            {"value": "+22%", "label": "Profit Margin"},
            {"value": "₦5M", "label": "Extra Revenue / Cycle"},
            {"value": "7 days", "label": "Optimal Window Notice"},
        ],
        "sections": [
            {
                "type": "text",
                "heading": "Executive Summary",
                "paragraphs": [
                    "Greenfield Farms raises 30,000 broilers per cycle in Ogun State. The birds "
                    "were healthy, but the farm consistently sold at the wrong time — either too "
                    "early, leaving weight on the table, or too late, when feed costs ate the "
                    "margin.",
                    "FlockIQ's AI sale-timing model combined growth curves, feed costs, and "
                    "market prices to recommend an optimal seven-day selling window. Acting on "
                    "it lifted profit margins by 22% — an extra ₦5 million per cycle.",
                ],
            },
            {
                "type": "text",
                "heading": "The Challenge",
                "paragraphs": [
                    "Knowing when to sell is one of the hardest calls in broiler production. "
                    "Greenfield wrestled with:",
                ],
                "bullets": [
                    "Selling too early and losing potential weight and revenue",
                    "Holding birds too long and burning margin on feed",
                    "No visibility into where market prices were heading",
                    "Decisions driven by cash-flow pressure rather than profit",
                ],
            },
            {
                "type": "quote",
                "text": (
                    "Every cycle we asked the same question — sell now or wait? We were "
                    "guessing, and guessing wrong was expensive either way."
                ),
                "author": "Mr. Tunde Bakare",
                "title": "Managing Partner, Greenfield Farms",
            },
            {
                "type": "text",
                "heading": "The Solution",
                "paragraphs": ["FlockIQ replaced the guesswork with a clear recommendation:"],
                "bullets": [
                    "<strong>AI Sale-Timing Model</strong> — Optimal selling window from growth, "
                    "feed cost, and price trends",
                    "<strong>Market Price Tracking</strong> — Regional price signals built into "
                    "the recommendation",
                    "<strong>Feed Efficiency Insights</strong> — Clear view of when extra feed "
                    "stops paying off",
                    "<strong>7-Day Advance Notice</strong> — Enough lead time to line up buyers "
                    "and logistics",
                ],
            },
            {
                "type": "results",
                "heading": "The Results",
                "cards": [
                    {"number": "+22%", "label": "Profit Margin"},
                    {"number": "₦5M", "label": "Extra Revenue / Cycle"},
                    {"number": "7 days", "label": "Advance Notice"},
                    {"number": "1.6", "label": "Improved FCR"},
                ],
                "paragraphs": [
                    "For its first guided cycle, FlockIQ recommended holding birds five extra "
                    "days to hit a forecast price peak. Greenfield lined up buyers in advance, "
                    "sold into the high, and recorded a 22% jump in margin — about ₦5 million "
                    "more than a typical cycle.",
                ],
            },
            {
                "type": "quote",
                "alt": True,
                "text": (
                    "FlockIQ told us exactly when to sell, and the price moved just like it "
                    "predicted. That seven-day heads-up changed our economics."
                ),
                "author": "Mr. Tunde Bakare",
                "title": "Managing Partner, Greenfield Farms",
            },
            {
                "type": "text",
                "heading": "What's Next",
                "paragraphs": [
                    "Greenfield is now staggering its flocks around FlockIQ's price forecasts so "
                    "that batches mature into different market windows, smoothing both revenue "
                    "and cash flow across the year.",
                ],
            },
            {
                "type": "text",
                "heading": "Key Takeaways",
                "bullets": [
                    "Optimal sale timing protects both weight gain and feed margin",
                    "Combining growth data with market prices beats gut-feel decisions",
                    "Advance notice lets farms negotiate better deals with buyers",
                    "Small timing improvements compound into millions over a year",
                ],
            },
        ],
    },
    {
        "slug": "enugu-smallholder-first-time-farmer",
        "emoji": "👨‍🌾 🤝",
        "card_badge": "ENUGU · 5,000 BIRDS",
        "card_title": "Smallholder Success: First-Time Farmer",
        "card_stats": ["📈 98% Survival Rate", "🍽️ 1.65 FCR", "💰 3x ROI First Cycle"],
        "card_excerpt": (
            "\"As a first-time farmer, FlockIQ's guided setup and daily alerts kept my birds "
            "healthy. I achieved a 98% survival rate and 1.65 feed conversion ratio — better "
            "than experienced farmers. I'm expanding to 10,000 birds next cycle.\""
        ),
        "farm_name": "Enugu Smallholder",
        "description": (
            "How a first-time farmer in Enugu achieved a 98% survival rate and 3x ROI in a "
            "single cycle with FlockIQ's guided setup and daily alerts."
        ),
        "detail_badge": "ENUGU · 5,000 BIRDS · BROILERS",
        "headline": "How a First-Time Farmer Achieved 98% Survival and 3x ROI in One Cycle",
        "hero_stats": [
            {"value": "98%", "label": "Survival Rate"},
            {"value": "1.65", "label": "Feed Conversion Ratio"},
            {"value": "3x", "label": "ROI First Cycle"},
        ],
        "sections": [
            {
                "type": "text",
                "heading": "Executive Summary",
                "paragraphs": [
                    "Chidi Eze had never raised a single bird before starting a 5,000-broiler "
                    "operation in Enugu. With no experience and no mentor nearby, the odds of a "
                    "costly first cycle were high.",
                    "FlockIQ's guided setup wizard and daily task alerts walked him through every "
                    "step. He finished his first cycle with a 98% survival rate, a 1.65 feed "
                    "conversion ratio, and a 3x return on investment — outperforming many "
                    "seasoned farmers.",
                ],
            },
            {
                "type": "text",
                "heading": "The Challenge",
                "paragraphs": [
                    "Starting from zero, Chidi faced the classic first-timer's risks:",
                ],
                "bullets": [
                    "No experience with brooding, feeding, or vaccination schedules",
                    "No way to know if something was going wrong until it was too late",
                    "Limited capital, so a failed first cycle could end the venture",
                    "No nearby expert to ask day-to-day questions",
                ],
            },
            {
                "type": "quote",
                "text": (
                    "I had the birds and the shed, but I honestly didn't know what to do each "
                    "day. One mistake in the first cycle could have wiped out my savings."
                ),
                "author": "Mr. Chidi Eze",
                "title": "Owner, Enugu Smallholder",
            },
            {
                "type": "text",
                "heading": "The Solution",
                "paragraphs": ["FlockIQ acted as Chidi's farm manager and mentor in one app:"],
                "bullets": [
                    "<strong>Guided Setup Wizard</strong> — Step-by-step configuration for a "
                    "first flock",
                    "<strong>Daily Task Alerts</strong> — Clear to-do list for feeding, water, "
                    "and checks every day",
                    "<strong>Vaccination Scheduler</strong> — Automatic reminders so no dose was "
                    "missed",
                    "<strong>Anomaly Detection</strong> — Early warnings whenever mortality or "
                    "intake drifted off track",
                ],
            },
            {
                "type": "results",
                "heading": "The Results",
                "cards": [
                    {"number": "98%", "label": "Survival Rate"},
                    {"number": "1.65", "label": "Feed Conversion Ratio"},
                    {"number": "3x", "label": "Return on Investment"},
                    {"number": "100%", "label": "Vaccination Compliance"},
                ],
                "paragraphs": [
                    "By simply following FlockIQ's daily tasks and acting on its alerts, Chidi "
                    "kept his flock healthy from brooding to sale. A 98% survival rate and a "
                    "1.65 FCR put his first cycle ahead of many experienced operators, and he "
                    "tripled his initial investment.",
                ],
            },
            {
                "type": "quote",
                "alt": True,
                "text": (
                    "FlockIQ told me what to do every single day. I went from knowing nothing to "
                    "running a farm that out-performed my neighbours."
                ),
                "author": "Mr. Chidi Eze",
                "title": "Owner, Enugu Smallholder",
            },
            {
                "type": "text",
                "heading": "What's Next",
                "paragraphs": [
                    "With a successful first cycle and reinvested profits, Chidi is doubling his "
                    "operation to 10,000 birds and plans to add a layer flock guided by FlockIQ's "
                    "egg-production tools.",
                ],
            },
            {
                "type": "text",
                "heading": "Key Takeaways",
                "bullets": [
                    "Guided setup lets first-time farmers start with confidence",
                    "Daily task alerts turn best practice into a simple routine",
                    "Early anomaly warnings protect limited starting capital",
                    "Good data and discipline can beat years of experience",
                ],
            },
        ],
    },
]

# Slug → case study, for O(1) detail lookups.
CASE_STUDIES_BY_SLUG = {cs["slug"]: cs for cs in CASE_STUDIES}
