DISEASE_PATTERNS = [
    {
        "name": "Newcastle Disease (ND)",
        "symptoms": ["respiratory", "nervous", "diarrhoea", "sudden_death", "drop_in_production"],
        "age_range": (7, 45),
        "mortality_threshold": 2.0,
        "description": (
            "Newcastle Disease is highly contagious. "
            "Symptoms: respiratory distress, twisted necks, "
            "sudden death. Notifiable disease in Nigeria."
        ),
        "actions": [
            "Isolate affected birds immediately",
            "Report to state veterinary services (notifiable disease)",
            "Do NOT sell or move birds",
            "Check vaccination records — ND vaccine should be given",
            "Increase biosecurity measures",
            "Log all deaths with cause = disease",
        ],
        "prevention": "Newcastle vaccine at day 7, 21, and booster at day 60.",
    },
    {
        "name": "Infectious Bronchitis (IB)",
        "symptoms": ["respiratory", "drop_in_production", "watery_eggs", "coughing"],
        "age_range": (1, 180),
        "mortality_threshold": 1.5,
        "description": (
            "IB causes respiratory distress and drops in production. "
            "Layer flocks can see 50% production drops."
        ),
        "actions": [
            "Improve ventilation immediately",
            "Provide electrolytes in drinking water",
            "Check and improve biosecurity",
            "Call a vet for antiviral support treatment",
        ],
        "prevention": "IB vaccine combined with Newcastle at day 1 and 14.",
    },
    {
        "name": "Gumboro (IBD)",
        "symptoms": ["lethargy", "ruffled_feathers", "watery_diarrhoea", "sudden_death"],
        "age_range": (3, 6),  # weeks
        "mortality_threshold": 3.0,
        "description": (
            "Gumboro destroys the immune system. "
            "Mainly affects 3–6 week old broilers. "
            "Surviving birds become immunosuppressed."
        ),
        "actions": [
            "Isolate and cull severely affected birds",
            "Electrolytes in water",
            "Call vet immediately — high mortality possible",
            "Clean and disinfect thoroughly after outbreak",
        ],
        "prevention": "Gumboro vaccine at day 10–14 and day 21.",
    },
    {
        "name": "Coccidiosis",
        "symptoms": ["bloody_diarrhoea", "lethargy", "poor_growth", "diarrhoea"],
        "age_range": (2, 8),  # weeks
        "mortality_threshold": 1.0,
        "description": (
            "Protozoan infection. Bloody droppings are "
            "characteristic. Major cause of poor FCR in broilers."
        ),
        "actions": [
            "Start Amprolium or Toltrazuril treatment immediately",
            "Improve litter management and ventilation",
            "Prevent wet litter — fix drinkers",
            "Segregate sick birds",
        ],
        "prevention": "Coccidiostats in feed or drinking water from day 1.",
    },
    {
        "name": "Fowl Typhoid / Salmonella",
        "symptoms": ["sudden_death", "diarrhoea", "lethargy", "ruffled_feathers"],
        "age_range": (1, 365),  # days
        "mortality_threshold": 2.0,
        "description": (
            "Bacterial infection. Can cause sudden high mortality. "
            "Zoonotic — can affect humans. Report to vet."
        ),
        "actions": [
            "Antibiotic treatment (consult vet for appropriate type)",
            "Strict biosecurity — disinfect equipment",
            "Avoid contact between farm workers and sick birds without PPE",
            "Report to veterinary services",
        ],
        "prevention": "Day-old chick vaccination where available.",
    },
]

# Maps checkbox form values to internal symptom keys
SYMPTOM_FORM_CHOICES = [
    ("respiratory", "Respiratory distress / coughing"),
    ("sudden_death", "Sudden death"),
    ("diarrhoea", "Diarrhoea"),
    ("bloody_diarrhoea", "Bloody diarrhoea"),
    ("lethargy", "Lethargy / ruffled feathers"),
    ("drop_in_production", "Drop in egg production"),
    ("poor_growth", "Poor growth / bad FCR"),
    ("nervous", "Twisted neck / nervous signs"),
    ("watery_eggs", "Watery eggs"),
    ("ruffled_feathers", "Ruffled feathers"),
    ("watery_diarrhoea", "Watery diarrhoea"),
]


class DiseaseDiagnosisEngine:
    """
    Pattern-based disease diagnosis for poultry.
    Returns ranked list of possible diseases based on symptoms + age + mortality.
    """

    def diagnose(
        self, symptoms: list, batch_age_weeks: int, mortality_rate: float = 0.0
    ) -> list:
        results = []

        for disease in DISEASE_PATTERNS:
            score = 0
            matched_symptoms = []

            age_min_days, age_max_days = disease["age_range"]
            # Gumboro and Coccidiosis age_range is in weeks (small numbers), others in days
            # Normalise: if max < 30, treat as weeks
            if age_max_days < 30:
                age_min_weeks = age_min_days
                age_max_weeks = age_max_days
            else:
                age_min_weeks = age_min_days / 7
                age_max_weeks = age_max_days / 7

            if age_min_weeks <= batch_age_weeks <= age_max_weeks:
                score += 2

            for symptom in symptoms:
                if symptom in disease["symptoms"]:
                    score += 3
                    matched_symptoms.append(symptom)

            if mortality_rate >= disease["mortality_threshold"]:
                score += 2

            if score >= 3:
                max_score = 2 + len(disease["symptoms"]) * 3 + 2
                confidence = min(95, int((score / max_score) * 100))
                results.append({
                    "disease": disease["name"],
                    "confidence": confidence,
                    "matched_symptoms": matched_symptoms,
                    "description": disease["description"],
                    "actions": disease["actions"],
                    "prevention": disease["prevention"],
                })

        return sorted(results, key=lambda x: x["confidence"], reverse=True)[:3]
