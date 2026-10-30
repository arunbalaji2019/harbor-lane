import hl_log

SERVICE = "invoicing"
VAT_RATE = 0.20


def issue_invoice(invoice_id, customer_id, net):
    vat = round(net * VAT_RATE, 2)
    total = round(net + vat, 2)
    hl_log.info(SERVICE, f"invoice {invoice_id} issued total={total}")
    hl_log.audit(SERVICE, "invoice_issued", invoice=invoice_id, customer=customer_id, net=net, vat=vat)
    return {"id": invoice_id, "total": total}
