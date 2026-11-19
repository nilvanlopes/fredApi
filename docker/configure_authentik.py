"""Run inside `ak shell` to provision Fred from this installation's FichasRPG.

Creates independent objects and refreshes the Fred branding on subsequent runs.
The source application is read-only. No credential is printed.
"""
from copy import deepcopy
from secrets import token_urlsafe

from django.db import transaction
from authentik.core.models import Application, Group, User
from authentik.flows.models import Flow, FlowStageBinding, Stage
from authentik.policies.models import PolicyBinding
from authentik.policies.expression.models import ExpressionPolicy
from authentik.providers.proxy.models import ProxyProvider
from authentik.sources.oauth.models import OAuthSource, OAuthSourcePropertyMapping
from authentik.brands.models import Brand
from authentik.outposts.models import Outpost


FRED_PUBLIC_URL = "https://fred.nilvanlopes.com"
FRED_LOGO = f"{FRED_PUBLIC_URL}/favicon.svg"
FRED_LOGIN_FLOWS = (
    'ak-flow-executor:is([slug="fred-authentication-flow"], [slug="fred-invalidation-flow"])'
)


def fred_login_css(source_css):
    # The FichasRPG CSS draws its own emblem and flow illustration over
    # Authentik's brand assets. Override those rules on Fred's two flows.
    return replace(source_css) + f"""
body:has({FRED_LOGIN_FLOWS}) {{
    background-color: #100f14;
}}
body:has({FRED_LOGIN_FLOWS})::before {{
    background:
        radial-gradient(ellipse at 50% 45%, #100f14 18%, #100f1400 80%),
        radial-gradient(circle, #d8b78332 1px, transparent 1.5px) center / 15px 15px,
        url("{FRED_PUBLIC_URL}/sports/volleyball.svg") 19% 24% / clamp(52px, 8vw, 124px) no-repeat,
        url("{FRED_PUBLIC_URL}/sports/basketball.svg") 81% 44% / clamp(56px, 9vw, 140px) no-repeat,
        url("{FRED_PUBLIC_URL}/sports/tennis.svg") 25% 75% / clamp(54px, 8vw, 124px) no-repeat,
        radial-gradient(ellipse at 55% 34%, #5b4731, #1b1820 72%) !important;
    filter: none;
    opacity: 1;
}}
:host(:is([slug="fred-authentication-flow"], [slug="fred-invalidation-flow"])) .pf-c-brand::before {{
    width: clamp(52px, 10vw, 72px);
    height: clamp(52px, 10vw, 72px);
    background-image: url("{FRED_LOGO}");
}}
"""


def replace(value):
    if isinstance(value, str):
        if value.startswith(("/files/", "/static/")):
            return value
        return (value.replace("https://fichasrpg.nilvanlopes.com/fichas", "https://fred.nilvanlopes.com/")
                .replace("fichasrpg", "fred").replace("fichamutantes", "fred")
                .replace("FichasRPG", "Fred").replace("Fichas RPG", "Fred")
                .replace("%2Ffichas", "%2F"))
    if isinstance(value, list):
        return [replace(v) for v in value]
    if isinstance(value, dict):
        return {k: replace(v) for k, v in value.items()}
    return value


mapping = {}
pairs = []


def clone(obj, lookup, **overrides):
    model = type(obj)
    existing = model.objects.filter(**lookup).first()
    if existing:
        mapping[obj.pk] = existing
        pairs.append((obj, existing))
        return existing
    values = {}
    for field in model._meta.fields:
        if field.primary_key or getattr(field.remote_field, "parent_link", False):
            continue
        if field.is_relation:
            related = getattr(obj, field.name)
            values[field.name] = mapping.get(related.pk, related) if related else None
        else:
            values[field.name] = replace(deepcopy(getattr(obj, field.name)))
    values.update(overrides)
    result = model.objects.create(**values)
    mapping[obj.pk] = result
    pairs.append((obj, result))
    return result


with transaction.atomic():
    users, _ = Group.objects.get_or_create(name="fred-users")
    admins, _ = Group.objects.get_or_create(name="fred-admins")
    mapping[Group.objects.get(name="fichasrpg-users").pk] = users
    source_app = Application.objects.get(slug="fichamutantes")
    flows = list(Flow.objects.filter(slug__startswith="fichasrpg"))
    for flow in flows:
        clone(flow, {"slug": replace(flow.slug)})
    for policy in ExpressionPolicy.objects.filter(name__startswith="fichasrpg"):
        clone(policy, {"name": replace(policy.name)})
    stages = list(Stage.objects.filter(name__startswith="fichasrpg").select_subclasses())
    for stage in stages:
        clone(stage, {"name": replace(stage.name)})
    google = OAuthSource.objects.get(slug="google-fichasrpg")
    clone(google, {"slug": "google-fred"}, name="Google Fred")
    google_fred = OAuthSource.objects.get(slug="google-fred")
    google_username, _ = OAuthSourcePropertyMapping.objects.update_or_create(
        name="fred-google-username-from-email",
        defaults={"expression": 'return {"username": info.get("email")}'},
    )
    google_fred.user_property_mappings.add(google_username)
    source_provider = ProxyProvider.objects.get(pk=source_app.provider_id)
    provider = clone(source_provider, {"name": "fred-forward-auth"},
                     name="fred-forward-auth", client_id=token_urlsafe(32),
                     client_secret=token_urlsafe(64), cookie_secret=token_urlsafe(32),
                     external_host="https://fred.nilvanlopes.com", internal_host="http://fred_web:8080")
    app = clone(source_app, {"slug": "fred"}, slug="fred", name="Fred",
                provider=provider, meta_launch_url="https://fred.nilvanlopes.com/")
    brand = Brand.objects.get(domain="login-fichasrpg.nilvanlopes.com")
    login_css = fred_login_css(brand.branding_custom_css)
    clone(brand, {"domain": "login-fred.nilvanlopes.com"}, default=False,
          domain="login-fred.nilvanlopes.com", branding_title="Fred", default_application=app,
          branding_logo=FRED_LOGO, branding_favicon=FRED_LOGO,
          branding_custom_css=login_css)
    for flow in flows:
        for binding in FlowStageBinding.objects.filter(target=flow):
            clone(binding, {"target": mapping[flow.pk], "order": binding.order})
    # Resolve references that pointed forward, e.g. identification -> password
    # and identification -> Google source; then reproduce M2M configuration.
    for old, new in pairs:
        changed = []
        for field in old._meta.fields:
            if not field.is_relation or field.primary_key or getattr(field.remote_field, "parent_link", False):
                continue
            related = getattr(old, field.name)
            if related and related.pk in mapping:
                setattr(new, field.name, mapping[related.pk])
                changed.append(field.name)
        if changed:
            new.save(update_fields=changed)
        for field in old._meta.many_to_many:
            relation = getattr(new, field.name)
            if field.name != "policies":
                relation.set([mapping.get(item.pk, item) for item in getattr(old, field.name).all()])
    for binding in PolicyBinding.objects.filter(target_id__in=list(mapping)):
        target = mapping[binding.target_id]
        policy = mapping.get(binding.policy_id, binding.policy) if binding.policy_id else None
        group = mapping.get(binding.group_id, binding.group) if binding.group_id else None
        PolicyBinding.objects.get_or_create(target=target, order=binding.order, defaults={
            "policy": policy, "group": group, "user": binding.user,
            "enabled": binding.enabled, "negate": binding.negate,
            "timeout": binding.timeout, "failure_result": binding.failure_result,
        })
    from authentik.stages.prompt.models import Prompt, PromptStage
    name_prompt, _ = Prompt.objects.get_or_create(name="fred-field-name", defaults={
        "field_key":"name", "label":"Nome", "type":"text", "required":True,
        "placeholder":"Seu nome", "initial_value":"", "order":-10,
    })
    PromptStage.objects.get(name="fred-enrollment-prompt").fields.add(name_prompt)
    # Registration creates ordinary members only. The existing pyu account
    # receives the initial management role, independent of Google registration.
    Brand.objects.filter(domain="login-fred.nilvanlopes.com").update(
        branding_title="Fred",
        branding_logo=FRED_LOGO,
        branding_favicon=FRED_LOGO,
        branding_default_flow_background=brand.branding_default_flow_background,
        branding_custom_css=login_css,
    )
    Flow.objects.filter(slug="fred-authentication-flow").update(title="Entre no Fred")
    from authentik.stages.redirect.models import RedirectStage
    RedirectStage.objects.filter(name="fred-logout-return").update(target_static="https://fred.nilvanlopes.com/")
    initial = User.objects.get(username="pyu")
    initial.groups.add(users, admins)
    outpost, _ = Outpost.objects.get_or_create(name="fred-outpost", defaults={
        "type": "proxy", "service_connection": None,
        "_config": {"log_level": "info", "authentik_host": "http://server:9000",
                    "authentik_host_browser": "https://login-fred.nilvanlopes.com",
                    "authentik_host_insecure": False},
    })
    outpost.providers.add(provider)
    outpost.token  # Materialize internally; secret is retrieved into .env separately.
print("Fred Authentik provisioned; source FichasRPG objects unchanged.")
print("Google callback: https://login-fred.nilvanlopes.com/source/oauth/callback/google-fred/")
