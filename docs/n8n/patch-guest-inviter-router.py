"""Patch one exported Fred WhatsApp Router workflow offline."""

from copy import deepcopy
import json
import sys


WORKFLOW_ID = "1KbREm2KQkUy87OO"
NORMALIZE = "Normalize Fred Message"
PROCESS = "Send Routed Message to Fred"
CHECK_SENDER = "Verificar remetente da lista"
LOOKUP_CONTACT = "Consultar contato do remetente no WAHA"
RECEIPT = "Registrar envio no Fred"
CHECK_CORRECTION = "Verificar correção do Fred"
CHECK_NOTICE = "Verificar aviso de não assinante"
SEND_CORRECTION = "Enviar lista corrigida pelo WAHA"
SEND_NOTICE = "Enviar aviso de não assinante"


def connection(node):
    return {"node": node, "type": "main", "index": 0}


def make_condition(template, node_id, condition_id, name, position, expression):
    node = deepcopy(template)
    node.update(id=node_id, name=name, position=position)
    checks = node["parameters"]["conditions"]["conditions"]
    if len(checks) != 1:
        raise ValueError(f"Template IF inesperado: {template['name']}")
    checks[0].update(id=condition_id, leftValue=expression)
    return node


def configure_sender_body(node, text_expression):
    """Configure an HTTP Request V3 JSON body using key/value expressions."""
    parameters = node["parameters"]
    parameters.pop("jsonBody", None)
    parameters["specifyBody"] = "keypair"
    parameters["bodyParameters"] = {
        "parameters": [
            {"name": "session", "value": "default"},
            {
                "name": "chatId",
                "value": "={{ $('Normalize Fred Message').first().json.chat_id }}",
            },
            {"name": "text", "value": "={{ " + text_expression + " }}"},
        ]
    }


def make_sender(template, node_id, name, position, text_expression):
    node = deepcopy(template)
    node.update(id=node_id, name=name, position=position, retryOnFail=False)
    configure_sender_body(node, text_expression)
    return node


def patch(workflow):
    if workflow.get("id") != WORKFLOW_ID:
        raise ValueError("A exportação não é o Fred WhatsApp Router esperado")
    nodes = workflow.get("nodes", [])
    by_name = {node["name"]: node for node in nodes}
    if len(by_name) != len(nodes):
        raise ValueError("Há nomes de nós duplicados no workflow")
    connections = workflow.setdefault("connections", {})

    required = (NORMALIZE, PROCESS, CHECK_SENDER, LOOKUP_CONTACT, RECEIPT,
                "Should Process Fred Message", "Enviar lista atualizada pelo WAHA")
    missing = [name for name in required if name not in by_name]
    if missing:
        raise ValueError(f"Nós esperados ausentes: {', '.join(missing)}")
    added_names = (CHECK_CORRECTION, CHECK_NOTICE, SEND_CORRECTION, SEND_NOTICE)
    if any(name in by_name for name in added_names):
        raise ValueError("O patch já foi aplicado ou há nós com nomes reservados")

    baseline = "Should Process Fred Message"
    expected = {"main": [[connection(CHECK_SENDER)]]}
    if connections.get(baseline) != expected:
        raise ValueError("Conexão atual do processamento de listas não corresponde à exportação esperada")
    if connections.get(CHECK_SENDER) != {
        "main": [[connection(LOOKUP_CONTACT)], [connection(PROCESS)]]
    } or connections.get(LOOKUP_CONTACT) != {"main": [[connection(PROCESS)]]}:
        raise ValueError("As conexões existentes de verificação/lookup foram alteradas")

    # Keep the WAHA-provided sender_name from the normalized webhook payload.
    # Add the contact directory name in its own field for guest attribution.
    by_name[PROCESS]["parameters"]["jsonBody"] = """={{ (() => {
  const payload = $('Normalize Fred Message').first().json.payload;
  if (!$('Consultar contato do remetente no WAHA').isExecuted || $json.error) {
    return { ...payload, sender_contact_name: null };
  }
  const senderContactName = [$json.name, $json.pushname]
    .find((value) => typeof value === 'string' && value.trim());
  return { ...payload, sender_contact_name: senderContactName?.trim() || null };
})() }}"""
    by_name[PROCESS]["parameters"]["url"] = "={{ $('Normalize Fred Message').first().json.targetUrl }}"

    condition_template = by_name[baseline]
    send_template = by_name["Enviar lista atualizada pelo WAHA"]
    new_nodes = [
        make_condition(
            condition_template, "f234778d-8235-4b09-9378-0ca394093ad1",
            "011ccf5d-10f9-4be4-a89c-8d24cab865cf", CHECK_CORRECTION, [1632, -320],
            "={{ typeof $('Send Routed Message to Fred').first().json.correction_text === 'string'"
            " && $('Send Routed Message to Fred').first().json.correction_text.trim()"
            " ? 'yes' : 'no' }}",
        ),
        make_condition(
            condition_template, "5969cc0c-53b6-4e8e-b4d8-524ebd79a255",
            "8c106b77-ecfb-409b-9849-b7b727a2ecdf", CHECK_NOTICE, [1904, -176],
            "={{ typeof $('Send Routed Message to Fred').first().json.correction_notice === 'string'"
            " && $('Send Routed Message to Fred').first().json.correction_notice.trim()"
            " ? 'yes' : 'no' }}",
        ),
        make_sender(
            send_template, "f94fdc81-304e-4265-a847-f1195ac6f945", SEND_CORRECTION,
            [2176, -320], "$('Send Routed Message to Fred').first().json.correction_text",
        ),
        make_sender(
            send_template, "046d8813-690e-42dc-9b65-0f100a8b95d2", SEND_NOTICE,
            [2176, -512], "$('Send Routed Message to Fred').first().json.correction_notice",
        ),
    ]
    workflow["nodes"].extend(new_nodes)

    connections[PROCESS] = {"main": [[connection(CHECK_CORRECTION)]]}
    connections[CHECK_CORRECTION] = {"main": [[connection(CHECK_NOTICE)], []]}
    connections[CHECK_NOTICE] = {
        "main": [[connection(SEND_NOTICE)], [connection(SEND_CORRECTION)]]
    }
    connections[SEND_NOTICE] = {"main": [[connection(SEND_CORRECTION)]]}
    # The correction HTTP node returns the WAHA receipt fields expected here.
    # Keep the same receipt node used by the scheduled weekly-list message.
    connections[SEND_CORRECTION] = {"main": [[connection(RECEIPT)]]}


if __name__ == "__main__":
    exported = json.load(sys.stdin)
    workflows = exported if isinstance(exported, list) else [exported]
    if len(workflows) != 1:
        raise SystemExit("Exporte apenas o Fred WhatsApp Router")
    patch(workflows[0])
    json.dump(exported, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
