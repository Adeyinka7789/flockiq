PLAN_FEATURES = {
    'trial': {
        'max_farms': 1,
        'max_active_batches': 1,
        'ai_daily_brief': False,
        'ai_anomaly_detection': False,
        'ai_theft_detection': False,
        'ai_egg_forecast': False,
        'ai_sale_timing': False,
        'ai_symptom_diagnosis': False,
        'ai_seasonal_demand': False,
        'exit_optimizer': False,
        'fcr_advisor': False,
        'pdf_export': False,
        'excel_export': False,
        'weather_alerts': True,
        'sms_notifications': False,
        'white_label': False,
        'roi_calculator': False,
        'team_members': 1,
    },
    'cycle': {
        'max_farms': 1,
        'max_active_batches': 3,
        'ai_daily_brief': False,
        'ai_anomaly_detection': False,
        'ai_theft_detection': False,
        'ai_egg_forecast': False,
        'ai_sale_timing': True,
        'ai_symptom_diagnosis': False,
        'ai_seasonal_demand': False,
        'exit_optimizer': True,
        'fcr_advisor': True,
        'pdf_export': False,
        'excel_export': False,
        'weather_alerts': True,
        'sms_notifications': False,
        'white_label': False,
        'roi_calculator': True,
        'team_members': 2,
    },
    'monthly': {
        'max_farms': 3,
        'max_active_batches': 10,
        'ai_daily_brief': True,
        'ai_anomaly_detection': True,
        'ai_theft_detection': True,
        'ai_egg_forecast': True,
        'ai_sale_timing': True,
        'ai_symptom_diagnosis': True,
        'ai_seasonal_demand': True,
        'exit_optimizer': True,
        'fcr_advisor': True,
        'pdf_export': True,
        'excel_export': True,
        'weather_alerts': True,
        'sms_notifications': True,
        'white_label': False,
        'roi_calculator': True,
        'team_members': 5,
    },
    'yearly': {
        'max_farms': 999,
        'max_active_batches': 999,
        'ai_daily_brief': True,
        'ai_anomaly_detection': True,
        'ai_theft_detection': True,
        'ai_egg_forecast': True,
        'ai_sale_timing': True,
        'ai_symptom_diagnosis': True,
        'ai_seasonal_demand': True,
        'exit_optimizer': True,
        'fcr_advisor': True,
        'pdf_export': True,
        'excel_export': True,
        'weather_alerts': True,
        'sms_notifications': True,
        'white_label': True,
        'roi_calculator': True,
        'team_members': 999,
    },
}


def get_plan_features(plan_tier: str) -> dict:
    return PLAN_FEATURES.get(plan_tier, PLAN_FEATURES['trial'])


def has_feature(org, feature: str) -> bool:
    features = get_plan_features(org.plan_tier)
    return features.get(feature, False)


def get_upgrade_plan(feature: str) -> str:
    for tier in ['trial', 'cycle', 'monthly', 'yearly']:
        if PLAN_FEATURES[tier].get(feature, False):
            return tier
    return 'yearly'
