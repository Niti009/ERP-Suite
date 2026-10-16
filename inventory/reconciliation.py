import csv
import io
import re
import unicodedata

from .models import Product


MAX_MANIFEST_SIZE = 2 * 1024 * 1024
MAX_MANIFEST_ROWS = 2000


def normalize_product_name(value):
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def reconcile_manifest(uploaded_file):
    if uploaded_file.size > MAX_MANIFEST_SIZE:
        raise ValueError("Manifest files must be 2 MB or smaller.")

    try:
        content = uploaded_file.read(MAX_MANIFEST_SIZE + 1).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Use a UTF-8 CSV file so product names can be matched reliably.") from exc
    if len(content.encode("utf-8")) > MAX_MANIFEST_SIZE:
        raise ValueError("Manifest files must be 2 MB or smaller.")

    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError("The CSV is empty. Add a header row and at least one product.") from exc
    except csv.Error as exc:
        raise ValueError("The CSV header could not be read. Check the file format.") from exc

    normalized_headers = [
        re.sub(r"[\s-]+", "_", header.strip().casefold()) for header in headers
    ]
    if not normalized_headers or any(not header for header in normalized_headers):
        raise ValueError("Every CSV column needs a header.")
    if len(set(normalized_headers)) != len(normalized_headers):
        raise ValueError("The CSV contains duplicate column headers.")

    header_indexes = {header: index for index, header in enumerate(normalized_headers)}
    id_index = next(
        (header_indexes[name] for name in ("product_id", "id") if name in header_indexes),
        None,
    )
    name_index = next(
        (
            header_indexes[name]
            for name in ("product_name", "name", "product")
            if name in header_indexes
        ),
        None,
    )
    quantity_index = next(
        (
            header_indexes[name]
            for name in ("quantity", "qty", "stock")
            if name in header_indexes
        ),
        None,
    )
    if id_index is None and name_index is None:
        raise ValueError("Add a product_id or product_name column to identify each product.")
    if quantity_index is None:
        raise ValueError("Add a quantity column with the stock count for each product.")

    products_by_id = {}
    products_by_name = {}
    for product in Product.objects.all().values("id", "name", "quantity"):
        product["normalized_name"] = normalize_product_name(product["name"])
        products_by_id[product["id"]] = product
        products_by_name.setdefault(product["normalized_name"], []).append(product)

    rows = []
    try:
        for values in reader:
            row_number = reader.line_num
            if not values or not any(value.strip() for value in values):
                continue
            if len(rows) >= MAX_MANIFEST_ROWS:
                raise ValueError(
                    f"Manifests can contain at most {MAX_MANIFEST_ROWS} non-empty rows."
                )

            padded = values + [""] * max(0, len(normalized_headers) - len(values))
            manifest_id = padded[id_index].strip() if id_index is not None else ""
            manifest_name = padded[name_index].strip() if name_index is not None else ""
            quantity_text = padded[quantity_index].strip()
            row = {
                "row_number": row_number,
                "manifest_id": manifest_id,
                "manifest_name": manifest_name,
                "quantity": None,
                "product_id": None,
                "product_name": "",
                "current_quantity": None,
                "difference": None,
                "match_method": "",
                "status": "invalid",
                "detail": "",
            }
            if len(values) > len(normalized_headers):
                row["detail"] = "This row has more values than the header defines."
            elif not quantity_text.isdecimal():
                row["detail"] = "Quantity must be a whole number of zero or more."
            elif id_index is not None and manifest_id and not manifest_id.isdecimal():
                row["detail"] = "Product ID must be a whole number."
            else:
                row["status"] = "unmatched"
                row["quantity"] = int(quantity_text)
                product = None
                if manifest_id:
                    numeric_id = int(manifest_id)
                    product = products_by_id.get(numeric_id)
                    if product:
                        if (
                            manifest_name
                            and normalize_product_name(manifest_name)
                            != product["normalized_name"]
                        ):
                            row["status"] = "conflict"
                            row["detail"] = (
                                "Product ID and product name point to different records. "
                                "Check the manifest before reconciling."
                            )
                        else:
                            row["match_method"] = "Product ID"
                    elif manifest_name:
                        named_matches = products_by_name.get(
                            normalize_product_name(manifest_name), []
                        )
                        if len(named_matches) == 1:
                            product = named_matches[0]
                            row["match_method"] = "Exact name (ID not found)"
                            row["detail"] = (
                                "The supplied ID was not found; an exact product-name "
                                "cross-reference was used."
                            )
                        elif len(named_matches) > 1:
                            row["status"] = "ambiguous"
                            row["detail"] = (
                                "This product name belongs to more than one inventory "
                                "record, and the supplied ID was not found."
                            )
                elif manifest_name:
                    named_matches = products_by_name.get(
                        normalize_product_name(manifest_name), []
                    )
                    if len(named_matches) == 1:
                        product = named_matches[0]
                        row["match_method"] = "Exact name"
                    elif len(named_matches) > 1:
                        row["status"] = "ambiguous"
                        row["detail"] = (
                            "This product name belongs to more than one inventory record. "
                            "Add a product_id column to identify the right one."
                        )
                else:
                    row["detail"] = "Add a product ID or product name for this row."

                if product and row["status"] != "conflict":
                    row.update(
                        {
                            "product_id": product["id"],
                            "product_name": product["name"],
                            "current_quantity": product["quantity"],
                            "difference": row["quantity"] - product["quantity"],
                            "status": (
                                "matched"
                                if row["quantity"] != product["quantity"]
                                else "synced"
                            ),
                        }
                    )
                elif row["status"] == "unmatched" and not row["detail"]:
                    row["detail"] = "No inventory product has this exact name or product ID."

            rows.append(row)
    except csv.Error as exc:
        raise ValueError("The CSV contains a malformed row. Check its delimiters and quotes.") from exc

    if not rows:
        raise ValueError("The CSV has no product rows to reconcile.")

    rows_by_product = {}
    for row in rows:
        if row["product_id"] is not None and row["status"] in {"matched", "synced"}:
            rows_by_product.setdefault(row["product_id"], []).append(row)
    for duplicate_rows in rows_by_product.values():
        if len(duplicate_rows) > 1:
            for row in duplicate_rows:
                row["status"] = "conflict"
                row["detail"] = (
                    "This product appears more than once in the manifest. Keep one row "
                    "so stock is not overwritten unpredictably."
                )

    counts = {
        "matched": sum(row["status"] == "matched" for row in rows),
        "synced": sum(row["status"] == "synced" for row in rows),
        "unresolved": sum(
            row["status"] in {"unmatched", "ambiguous", "conflict", "invalid"}
            for row in rows
        ),
    }
    return {"rows": rows, "counts": counts}
