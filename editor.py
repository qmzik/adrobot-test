from copy import deepcopy

import keitaro as kt


class EditError(ValueError):
    pass


def snapshot(stream):
    return [{k: row[k] for k in ("offer_id", "state", "share")} for row in stream["offers"]]


def draft_rows(offers):
    return [dict(row, pinned=False, removed=False) for row in offers]


def payload(rows):
    return [{k: row[k] for k in ("offer_id", "state", "share")} for row in rows if not row["removed"]]


def same_offers(left, right):
    return sorted(left, key=lambda r: r["offer_id"]) == sorted(right, key=lambda r: r["offer_id"])


def balance(rows):
    active = [r for r in rows if not r["removed"] and r["state"] == "active"]
    if not active:
        raise EditError("Оставьте в потоке хотя бы один активный оффер.")
    free = [r for r in active if not r["pinned"]]
    remaining = 100 - sum(r["share"] for r in active if r["pinned"])
    if remaining < 0 or (not free and remaining != 0):
        raise EditError("Закреплённые доли не позволяют распределить 100%. Измените долю или снимите закрепление.")
    if free:
        share, extra = divmod(remaining, len(free))
        for index, row in enumerate(free):
            row["share"] = share + int(index < extra)


def edit(draft, action, offer_id, share):
    rows = deepcopy(draft.rows)
    row = next((r for r in rows if r["offer_id"] == offer_id), None)
    if action == "add":
        if row or str(offer_id) not in draft.catalog:
            raise EditError("Выберите доступный оффер, которого ещё нет в потоке.")
        rows.append(dict(offer_id=offer_id, state="active", share=0, removed=False, pinned=False))
    elif row is None:
        raise EditError("Оффер отсутствует в черновике.")
    elif action == "restore" and row["removed"]:
        row["removed"] = False
    elif action == "remove" and not row["removed"]:
        row["removed"] = True
    elif action == "pin" and not row["removed"] and row["state"] == "active":
        if share is None or not 0 <= share <= 100:
            raise EditError("Доля должна быть целым числом от 0 до 100.")
        row.update(pinned=True, share=share)
    elif action == "unpin" and row["pinned"] and not row["removed"]:
        row["pinned"] = False
    else:
        raise EditError("Действие недоступно для этого оффера.")
    balance(rows)
    draft.rows = rows


def load_stream(campaign_id, stream_id):
    stream = kt.api("GET", f"streams/{stream_id}")
    if stream["campaign_id"] != campaign_id or stream["schema"] != "landings":
        raise EditError("Выбранный поток не является потоком офферов этой кампании.")
    return stream


def publish(draft):
    desired = payload(draft.rows)
    shares = [r["share"] for r in desired if r["state"] == "active"]
    if sum(shares) != 100 or any(s < 0 or s > 100 for s in shares):
        raise EditError("Сумма долей активных офферов должна равняться 100%.")
    current = snapshot(load_stream(draft.campaign_id, draft.stream_id))
    if not same_offers(current, desired):
        if not same_offers(current, draft.baseline):
            raise EditError("Состав или доли уже изменились в Keitaro. Загрузите свежий поток.")
        added = {r["offer_id"] for r in desired} - {r["offer_id"] for r in draft.baseline}
        if added and not added.issubset({o["id"] for o in kt.offers()}):
            raise EditError("Один из добавленных офферов больше недоступен.")
        kt.api("PUT", f"streams/{draft.stream_id}", {"offers": desired})
        current = snapshot(load_stream(draft.campaign_id, draft.stream_id))
        if not same_offers(current, desired):
            raise EditError("Keitaro вернул другой состав или доли после публикации. Проверьте поток.")
    draft.baseline = current
    draft.rows = [r for r in draft.rows if not r["removed"]]
    draft.published = True
