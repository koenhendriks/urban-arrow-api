from enum import StrEnum

# Extracted from com.urbanarrow.connected 5.2.1 (ConnectApp / LibraryConfig).
API_BASE_URL = "https://app.connected.pon.bike/api/"
AUTH0_DOMAIN = "consumer.login.pon.bike"
AUTH0_CLIENT_ID = "i2ype1HhtU4rg4LKRdBKgldnfVbVwrG6"
AUTH0_AUDIENCE = "https://app.connected.pon.bike/"
AUTH0_SCOPE = "openid profile offline_access email"
# Auth0 Android SDK builds the callback as {scheme}://{domain}/android/{package}/callback.
# The tenant only accepts registered callbacks, so we must reuse the app's one.
AUTH0_REDIRECT_URI = (
    "urbanarrow://consumer.login.pon.bike/android/com.urbanarrow.connected/callback"
)

# The same backend serves several Pon brands; "UA" selects Urban Arrow.
MANUFACTURER_ID = "UA"
CLIENT_TYPE = "ANDROID"
PRODUCTION_PROFILE_IMAGE_URL = (
    "https://app.connected.pon.bike/api/v1/productionprofiles/{profile_id}/image"
)


class BikeSetting(StrEnum):
    AUTO_PROTECTION = "AUTO_PROTECTION"
    NOTIFICATION_PROTECTION_ACTIVATED = "NOTIFICATION_PROTECTION_ACTIVATED"
    MODULE_BATTERY_MANAGEMENT = "MODULE_BATTERY_MANAGEMENT"
    NOTIFICATION_BATTERY_FULL = "NOTIFICATION_BATTERY_FULL"
    NOTIFICATION_BATTERY_LOW = "NOTIFICATION_BATTERY_LOW"
    NOTIFICATION_MODULE_BATTERY_LOW = "NOTIFICATION_MODULE_BATTERY_LOW"


class ActivityPeriod(StrEnum):
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    YEAR = "YEAR"
