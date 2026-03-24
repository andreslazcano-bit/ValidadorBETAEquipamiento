from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any
import unicodedata

import pandas as pd


EXPECTED_SHEETS = [
    "Especialidad",
    "Innovacion",
    "Evaluacion 1",
    "Evaluacion 2",
    "Resumen proyecto especialidad",
    "Propuesta habilitacion",
]

ALLOWED_INNOV_KIND = {
    "MAQUINAS Y EQUIPOS",
    "INSTRUMENTOS",
    "HERRAMIENTAS, IMPLEMENTOS Y UTENSILIOS",
    "MATERIAL INTERACTIVO (DIDACTICO)",
    "SOFTWARE",
}

ALLOWED_INNOV_TYPE = {"PROFUNDIZAR", "COMPLEMENTAR"}

# Rangos de financiamiento por matrícula (acorde a convocatoria Subsecretaría)
# Estructura: (matrícula_desde, matrícula_hasta) -> (monto_minimo, monto_maximo)
BUDGET_RANGES = [
    ((10, 30), (15_000_000, 60_000_000)),
    ((31, 60), (15_000_000, 78_000_000)),
    ((61, 90), (15_000_000, 96_000_000)),
    ((91, 120), (15_000_000, 114_000_000)),
    ((121, 150), (15_000_000, 132_000_000)),
]

MATRICULA_DIFF_WARNING_THRESHOLD = 0.10

RULE_DESCRIPTIONS = {
    "STR-001": "No existe hoja que comience con 'Especialidad'",
    "STR-002": "No existe hoja que comience con 'Innovacion'",
    "STR-003": "No existe hoja 'Resumen proyecto especialidad'",
    "STR-004": "No existe hoja 'Propuesta habilitacion'",
    "STR-005": "No existe hoja que comience con 'Evaluacion 1'",
    "STR-006": "No existe hoja que comience con 'Evaluacion 2'",
    "ESP-001": "Fila con datos sin nombre corto del recurso",
    "ESP-002": "El campo 'incluido al proyecto' debe ser SI o NO",
    "ESP-003": "Si está incluido, el tipo de recurso debe ser REGULAR o ALTERNATIVO",
    "ESP-004": "Recurso ALTERNATIVO sin función pedagógica justificada",
    "ESP-005": "Recurso incluido con cantidad vacía o <= 0",
    "ESP-006": "Recurso incluido con valor unitario vacío o <= 0",
    "ESP-007": "Valor total no coincide con cantidad x valor unitario",
    "ESP-008": "Cantidad solicitada supera índice de uso reportado",
    "ESP-009": "Fila marcada como NO incluye una cantidad mayor a 0",
    "ESP-010": "Error leyendo hoja Especialidad",
    "EV1-001": "Recurso ALTERNATIVO sin justificación pedagógica válida",
    "EV1-002": "No se pudo determinar margen de índice de uso para comparación",
    "EV1-003": "Cantidad > 0 con margen de índice de uso no válido",
    "EV1-004": "Cantidad solicitada supera el margen permitido de índice de uso",
    "EV1-010": "Error leyendo hoja Evaluación 1",
    "EV2-001": "Campos obligatorios vacíos o inválidos en Evaluación 2",
    "EV2-002": "Tipo de recurso fuera de lista desplegable",
    "EV2-003": "Tipo de innovación fuera de lista (Profundizar/Complementar)",
    "EV2-004": "Justificación del propósito sin texto válido",
    "EV2-005": "Sin justificación explícita de cantidad solicitada",
    "EV2-006": "Cantidad de innovación vacía o <= 0",
    "EV2-007": "Valor unitario de innovación vacío o <= 0",
    "EV2-008": "Total no coincide con cantidad x valor",
    "EV2-010": "Error leyendo hoja Evaluación 2",
    "RES-001": "Presupuesto total fuera de rango según matrícula",
    "RES-002": "Presupuesto de HABILITACIÓN supera 10% del total solicitado",
    "RES-003": "Error leyendo hoja Resumen proyecto especialidad",
    "RES-004": "Diferencia significativa entre matrícula oficial y matrícula declarada",
    "BUD-001": "Total solicitado supera el presupuesto máximo configurado",
}

SEVERITY_CRITICAL = "Crítico"
SEVERITY_WARNING = "Revisar"
SEVERITY_INFO = "Informativo"


@dataclass
class Finding:
    severity: str
    rule_id: str
    sheet: str
    row: int | None
    field: str
    message: str


@dataclass
class ValidationResult:
    file_name: str
    sha256: str
    findings: list[Finding]
    stats: dict[str, Any]


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().lower()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return _norm_text(value) == ""


def _is_zero_like(value: Any) -> bool:
    if _is_blank(value):
        return True
    num = _to_number(value)
    if num is not None and abs(num) < 1e-12:
        return True
    return False


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _add(findings: list[Finding], severity: str, rule_id: str, sheet: str, row: int | None, field: str, message: str) -> None:
    findings.append(
        Finding(
            severity=severity,
            rule_id=rule_id,
            sheet=sheet,
            row=row,
            field=field,
            message=message,
        )
    )


def _find_sheet_name(sheet_names: list[str], starts_with: str) -> str | None:
    starts_with_low = _norm_key(starts_with)
    for name in sheet_names:
        if _norm_key(name).startswith(starts_with_low):
            return name
    return None


def _extract_specialty_from_sheet_name(sheet_name: str | None) -> str:
    if not sheet_name:
        return ""
    prefix = "Especialidad"
    if sheet_name.lower().startswith(prefix.lower()):
        return sheet_name[len(prefix):].strip(" _-")
    return sheet_name.strip()


def _iter_especialidad_rows(df: pd.DataFrame):
    header_idx: int | None = None
    for idx, row in df.iterrows():
        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        col_e = _norm_key(_norm_text(row.get(4, "")))
        if col_a == "tipo" and col_b == "nombre" and "incluido" in col_e:
            header_idx = idx
            break

    start_idx = (header_idx + 1) if header_idx is not None else 0
    empty_streak = 0
    for idx in range(start_idx, len(df)):
        row = df.iloc[idx]
        is_row_blank = all(_is_blank(row.get(col)) for col in range(0, 10))
        if is_row_blank:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        has_resource_identity = any(not _is_blank(row.get(col)) for col in range(0, 4))
        if not has_resource_identity:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        empty_streak = 0
        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        col_e = _norm_key(_norm_text(row.get(4, "")))
        if col_a == "tipo" and col_b == "nombre" and "incluido" in col_e:
            continue

        yield idx


def _iter_innovacion_rows(df: pd.DataFrame):
    header_idx: int | None = None
    for idx, row in df.iterrows():
        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        if col_a == "tipo" and col_b == "nombre":
            header_idx = idx
            break

    start_idx = (header_idx + 1) if header_idx is not None else 0
    empty_streak = 0
    for idx in range(start_idx, len(df)):
        row = df.iloc[idx]

        is_row_blank = all(_is_blank(row.get(col)) for col in range(0, 9))
        if is_row_blank:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        has_identity = any(not _is_zero_like(row.get(col)) for col in range(0, 4))
        if not has_identity:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        empty_streak = 0

        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        if col_a == "tipo" and col_b == "nombre":
            continue

        yield idx


def _iter_eval1_rows(df: pd.DataFrame):
    header_idx: int | None = None
    for idx, row in df.iterrows():
        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        col_e = _norm_key(_norm_text(row.get(4, "")))
        if col_a == "tipo" and col_b == "nombre" and "incluido" in col_e:
            header_idx = idx
            break

    start_idx = (header_idx + 1) if header_idx is not None else 10
    empty_streak = 0
    for idx in range(start_idx, len(df)):
        row = df.iloc[idx]
        is_row_blank = all(_is_blank(row.get(col)) for col in range(0, 30))
        if is_row_blank:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        has_resource_identity = any(not _is_blank(row.get(col)) for col in range(0, 4))
        has_summary_identity = any(not _is_blank(row.get(col)) for col in range(20, 23))
        if not has_resource_identity and not has_summary_identity:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        empty_streak = 0
        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        col_e = _norm_key(_norm_text(row.get(4, "")))
        if col_a == "tipo" and col_b == "nombre" and "incluido" in col_e:
            continue

        yield idx


def _iter_eval2_rows(df: pd.DataFrame):
    header_idx: int | None = None
    for idx, row in df.iterrows():
        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        col_e = _norm_key(_norm_text(row.get(4, "")))
        if col_a == "tipo" and col_b == "nombre" and "innovacion" in col_e:
            header_idx = idx
            break

    start_idx = (header_idx + 1) if header_idx is not None else 10
    empty_streak = 0
    for idx in range(start_idx, len(df)):
        row = df.iloc[idx]

        is_row_blank = all(_is_blank(row.get(col)) for col in range(0, 9))
        if is_row_blank:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        has_identity = any(not _is_zero_like(row.get(col)) for col in range(0, 4))
        if not has_identity:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue

        empty_streak = 0

        col_a = _norm_key(_norm_text(row.get(0, "")))
        col_b = _norm_key(_norm_text(row.get(1, "")))
        if col_a == "tipo" and col_b == "nombre":
            continue

        yield idx


def _has_meaningful_text_justification(value: Any) -> bool:
    text = _norm_text(value)
    if not text:
        return False

    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return False

    letter_matches = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", normalized)
    if len(letter_matches) < 12:
        return False

    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", normalized)
    if len(words) < 3:
        return False

    non_space_chars = len(re.sub(r"\s+", "", normalized))
    if non_space_chars == 0:
        return False

    letters_ratio = len(letter_matches) / non_space_chars
    if letters_ratio < 0.45:
        return False

    return True


def _has_quantity_justification_signal(justification: str, qty: float | None) -> bool:
    text = _norm_key(justification)
    if not text:
        return False

    keywords = ["cantidad", "cantidades", "matricula", "estudiante", "estudiantes", "cupo", "cursos"]
    if any(word in text for word in keywords):
        return True

    if qty is not None and qty > 0:
        qty_int = int(round(qty))
        qty_tokens = {str(qty_int), str(qty), str(float(qty_int)).replace(".0", "")}
        if any(token and token in text for token in qty_tokens):
            return True

    return False


def _get_budget_range(matricula: float | None) -> tuple[float, float] | None:
    """Retorna (monto_minimo, monto_maximo) según rango de matrícula, o None si no existe rango."""
    if matricula is None or matricula < 10:
        return None
    
    for (rango_min, rango_max), (monto_min, monto_max) in BUDGET_RANGES:
        if rango_min <= matricula <= rango_max:
            return (monto_min, monto_max)
    
    return None


def validate_workbook(file_name: str, file_bytes: bytes, sha256: str, budget_limit: float | None = None) -> ValidationResult:
    findings: list[Finding] = []
    try:
        xls = pd.ExcelFile(BytesIO(file_bytes))
        sheet_names = xls.sheet_names
    except Exception as ex:
        return ValidationResult(
            file_name=file_name,
            sha256=sha256,
            findings=[Finding(
                severity=SEVERITY_CRITICAL,
                rule_id="SYS-001",
                sheet="(workbook)",
                row=None,
                field="archivo",
                message=f"No se puede leer archivo: {ex}",
            )],
            stats={"critical_count": 1, "warning_count": 0, "info_count": 0},
        )

    special_sheet = _find_sheet_name(sheet_names, "Especialidad")
    innov_sheet = _find_sheet_name(sheet_names, "Innovacion")
    eval1_sheet = _find_sheet_name(sheet_names, "Evaluacion 1")
    eval2_sheet = _find_sheet_name(sheet_names, "Evaluacion 2")
    resumen_sheet = _find_sheet_name(sheet_names, "Resumen proyecto especialidad")
    habil_sheet = _find_sheet_name(sheet_names, "Propuesta habilitacion")

    if not special_sheet:
        _add(findings, SEVERITY_CRITICAL, "STR-001", "(workbook)", None, "sheet", "No existe hoja que comience con 'Especialidad'.")
    if not innov_sheet:
        _add(findings, SEVERITY_CRITICAL, "STR-002", "(workbook)", None, "sheet", "No existe hoja que comience con 'Innovacion'.")
    if not eval1_sheet:
        _add(findings, SEVERITY_WARNING, "STR-005", "(workbook)", None, "sheet", "No existe hoja que comience con 'Evaluacion 1'.")
    if not eval2_sheet:
        _add(findings, SEVERITY_WARNING, "STR-006", "(workbook)", None, "sheet", "No existe hoja que comience con 'Evaluacion 2'.")
    if not resumen_sheet:
        _add(findings, SEVERITY_WARNING, "STR-003", "(workbook)", None, "sheet", "No existe hoja 'Resumen proyecto especialidad'.")
    if not habil_sheet:
        _add(findings, SEVERITY_WARNING, "STR-004", "(workbook)", None, "sheet", "No existe hoja 'Propuesta habilitacion'.")

    total_regular = 0.0
    total_innov = 0.0
    total_habil = 0.0
    rows_regular = 0
    rows_innov = 0
    rows_eval2 = 0
    rbd_value = ""
    especialidad_value = _extract_specialty_from_sheet_name(special_sheet)

    if special_sheet:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=special_sheet, header=None)
            for row_idx in _iter_especialidad_rows(df):
                rows_regular += 1
                row = df.iloc[row_idx]
                
                included = _norm_text(row.get(4, "")).upper()
                resource_type = _norm_text(row.get(5, "")).upper()
                justification = _norm_text(row.get(6, ""))
                indice_val = _to_number(row.get(2))
                qty_val = _to_number(row.get(7))
                unit_val = _to_number(row.get(8))
                total_val = _to_number(row.get(9))
                short_name = _norm_text(row.get(3, ""))

                excel_row = row_idx + 1

                if not short_name:
                    _add(findings, SEVERITY_WARNING, "ESP-001", special_sheet, excel_row, "nombre_corto", "Fila con datos sin nombre corto del recurso.")

                if included not in {"SI", "NO"}:
                    _add(findings, SEVERITY_WARNING, "ESP-002", special_sheet, excel_row, "incluido", "El campo 'incluido al proyecto' debe ser SI o NO.")

                if included == "SI" and resource_type not in {"REGULAR", "ALTERNATIVO"}:
                    _add(findings, SEVERITY_WARNING, "ESP-003", special_sheet, excel_row, "tipo_recurso", "Si esta incluido, el tipo de recurso debe ser REGULAR o ALTERNATIVO.")

                if resource_type == "ALTERNATIVO" and not justification:
                    _add(findings, SEVERITY_CRITICAL, "ESP-004", special_sheet, excel_row, "funcion_pedagogica", "Recurso ALTERNATIVO sin funcion pedagogica justificada.")

                if included == "SI":
                    if qty_val is None or qty_val <= 0:
                        _add(findings, SEVERITY_CRITICAL, "ESP-005", special_sheet, excel_row, "cantidad", "Recurso incluido con cantidad vacia o <= 0.")
                    if unit_val is None or unit_val <= 0:
                        _add(findings, SEVERITY_CRITICAL, "ESP-006", special_sheet, excel_row, "valor_unitario", "Recurso incluido con valor unitario vacio o <= 0.")
                    if qty_val is not None and unit_val is not None:
                        expected = qty_val * unit_val
                        if total_val is not None and abs(expected - total_val) > 1:
                            _add(findings, SEVERITY_WARNING, "ESP-007", special_sheet, excel_row, "valor_total", "Valor total no coincide con cantidad x valor unitario.")
                        total_regular += expected
                    if qty_val is not None and indice_val is not None and indice_val > 0 and qty_val > indice_val:
                        _add(findings, SEVERITY_WARNING, "ESP-008", special_sheet, excel_row, "cantidad", "Cantidad solicitada supera indice de uso reportado.")

                if included == "NO" and qty_val not in (None, 0):
                    _add(findings, SEVERITY_INFO, "ESP-009", special_sheet, excel_row, "cantidad", "Fila marcada como NO incluye una cantidad mayor a 0.")
        except Exception as ex:
            _add(findings, SEVERITY_WARNING, "ESP-010", special_sheet, None, "lectura", f"Error leyendo hoja: {ex}")

    if eval1_sheet:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=eval1_sheet, header=None)
            for row_idx in _iter_eval1_rows(df):
                row = df.iloc[row_idx]
                excel_row = row_idx + 1

                included = _norm_text(row.get(4, "")).upper()
                resource_type = _norm_text(row.get(5, "")).upper()
                justification = row.get(6, "")

                if included == "SI" and resource_type == "ALTERNATIVO":
                    if not _has_meaningful_text_justification(justification):
                        _add(
                            findings,
                            SEVERITY_CRITICAL,
                            "EV1-001",
                            eval1_sheet,
                            excel_row,
                            "funcion_pedagogica",
                            "En Evaluacion 1, recurso ALTERNATIVO sin justificacion pedagogica valida (texto real).",
                        )

                qty_solicitada = _to_number(row.get(24))
                indice_x_15 = _to_number(row.get(26))

                if qty_solicitada is None:
                    continue

                if indice_x_15 is None:
                    _add(
                        findings,
                        SEVERITY_WARNING,
                        "EV1-002",
                        eval1_sheet,
                        excel_row,
                        "indice_x_1_5",
                        "No se pudo determinar el margen de indice de uso (columna AA) para comparar cantidad solicitada.",
                    )
                    continue

                if indice_x_15 <= 0 and qty_solicitada > 0:
                    _add(
                        findings,
                        SEVERITY_WARNING,
                        "EV1-003",
                        eval1_sheet,
                        excel_row,
                        "cantidad_solicitada",
                        "Cantidad solicitada mayor a 0 con margen de indice de uso no valido (<= 0).",
                    )
                    continue

                if qty_solicitada > (indice_x_15 + 1e-9):
                    _add(
                        findings,
                        SEVERITY_WARNING,
                        "EV1-004",
                        eval1_sheet,
                        excel_row,
                        "cantidad_solicitada",
                        f"Cantidad solicitada ({qty_solicitada:g}) supera el margen permitido de indice de uso ({indice_x_15:g}).",
                    )
        except Exception as ex:
            _add(findings, SEVERITY_WARNING, "EV1-010", eval1_sheet, None, "lectura", f"Error leyendo hoja: {ex}")

    if eval2_sheet:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=eval2_sheet, header=None)
            for row_idx in _iter_eval2_rows(df):
                rows_eval2 += 1
                row = df.iloc[row_idx]
                excel_row = row_idx + 1

                tipo = _norm_text(row.get(0, ""))
                nombre = _norm_text(row.get(1, ""))
                descripcion = _norm_text(row.get(2, ""))
                objetivo = _norm_text(row.get(3, ""))
                tipo_innov = _norm_text(row.get(4, ""))
                justificacion = _norm_text(row.get(5, ""))
                cantidad = _to_number(row.get(6))
                valor = _to_number(row.get(7))
                total = _to_number(row.get(8))

                required_fields = {
                    "tipo": tipo,
                    "nombre": nombre,
                    "descripcion": descripcion,
                    "objetivo_aprendizaje": objetivo,
                    "tipo_innovacion": tipo_innov,
                    "proposito_y_justificacion_cantidad": justificacion,
                }
                for field, value in required_fields.items():
                    if not value or _is_zero_like(value):
                        _add(findings, SEVERITY_CRITICAL, "EV2-001", eval2_sheet, excel_row, field, f"Campo obligatorio vacio o invalido: {field}.")

                tipo_key = _norm_key(tipo).upper()
                if tipo and tipo_key not in ALLOWED_INNOV_KIND:
                    _add(findings, SEVERITY_WARNING, "EV2-002", eval2_sheet, excel_row, "tipo", "Valor fuera de lista desplegable para tipo de recurso de innovacion.")

                tipo_innov_key = _norm_key(tipo_innov).upper()
                if tipo_innov and tipo_innov_key not in ALLOWED_INNOV_TYPE:
                    _add(findings, SEVERITY_WARNING, "EV2-003", eval2_sheet, excel_row, "tipo_innovacion", "Tipo de innovacion fuera de lista desplegable (Profundizar/Complementar).")

                if not _has_meaningful_text_justification(justificacion):
                    _add(findings, SEVERITY_CRITICAL, "EV2-004", eval2_sheet, excel_row, "proposito", "La justificacion del proposito de innovacion no contiene texto valido.")

                if not _has_quantity_justification_signal(justificacion, cantidad):
                    _add(findings, SEVERITY_WARNING, "EV2-005", eval2_sheet, excel_row, "justificacion_cantidad", "No se observa justificacion explicita de la cantidad solicitada.")

                if cantidad is None or cantidad <= 0:
                    _add(findings, SEVERITY_CRITICAL, "EV2-006", eval2_sheet, excel_row, "cantidad", "Cantidad de innovacion vacia o <= 0.")

                if valor is None or valor <= 0:
                    _add(findings, SEVERITY_CRITICAL, "EV2-007", eval2_sheet, excel_row, "valor", "Valor unitario de innovacion vacio o <= 0.")

                if cantidad is not None and valor is not None:
                    expected = cantidad * valor
                    if total is not None and abs(expected - total) > 1:
                        _add(findings, SEVERITY_WARNING, "EV2-008", eval2_sheet, excel_row, "total", "Total no coincide con cantidad x valor en Evaluacion 2.")
        except Exception as ex:
            _add(findings, SEVERITY_WARNING, "EV2-010", eval2_sheet, None, "lectura", f"Error leyendo hoja: {ex}")

    if resumen_sheet:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=resumen_sheet, header=None)
            if len(df) >= 2 and len(df.columns) >= 2:
                rbd_cell = _norm_text(df.iloc[1, 1])  # B2
                if rbd_cell:
                    rbd_value = rbd_cell
            
            # Leer celdas clave: D2 (matrícula oficial), F2 (matrícula actual), F8 (total), D7 (habilitación)
            matricula_oficial = None
            matricula_actual = None
            total_solicitado = None
            total_habil_resumen = None

            if len(df) >= 2 and len(df.columns) >= 4:
                matricula_oficial = _to_number(df.iloc[1, 3])  # D2
            
            if len(df) >= 2 and len(df.columns) >= 6:
                matricula_actual = _to_number(df.iloc[1, 5])  # F2

            # Validar RES-004: Diferencia relativa entre matrícula oficial y declarada
            if (
                matricula_oficial is not None
                and matricula_oficial > 0
                and matricula_actual is not None
            ):
                diff_ratio = abs(matricula_actual - matricula_oficial) / matricula_oficial
                if diff_ratio > MATRICULA_DIFF_WARNING_THRESHOLD:
                    _add(
                        findings,
                        SEVERITY_WARNING,
                        "RES-004",
                        resumen_sheet,
                        2,
                        "matricula_actual",
                        (
                            f"Matrícula declarada ({matricula_actual:g}) difiere de la oficial "
                            f"({matricula_oficial:g}) en {diff_ratio * 100:.1f}%, sobre el umbral de "
                            f"{MATRICULA_DIFF_WARNING_THRESHOLD * 100:.0f}% para revisión."
                        ),
                    )
            
            if len(df) >= 8 and len(df.columns) >= 6:
                total_solicitado = _to_number(df.iloc[7, 5])  # F8
            
            if len(df) >= 7 and len(df.columns) >= 4:
                total_habil_resumen = _to_number(df.iloc[6, 3])  # D7
            
            # Validar RES-001: Total debe estar dentro del rango según matrícula
            if matricula_actual is not None and total_solicitado is not None:
                budget_range = _get_budget_range(matricula_actual)
                
                if budget_range is None:
                    _add(
                        findings,
                        SEVERITY_WARNING,
                        "RES-001",
                        resumen_sheet,
                        2,
                        "matricula_actual",
                        f"Matrícula actual ({matricula_actual:g}) fuera de rangos definidos (10-150).",
                    )
                else:
                    monto_min, monto_max = budget_range
                    if total_solicitado < (monto_min - 1e-9):
                        _add(
                            findings,
                            SEVERITY_CRITICAL,
                            "RES-001",
                            resumen_sheet,
                            8,
                            "total_solicitado",
                            f"Total solicitado ({total_solicitado:g}) es menor que el mínimo permitido para matrícula {matricula_actual:g}: ${monto_min:,.0f}.",
                        )
                    elif total_solicitado > (monto_max + 1e-9):
                        _add(
                            findings,
                            SEVERITY_CRITICAL,
                            "RES-001",
                            resumen_sheet,
                            8,
                            "total_solicitado",
                            f"Total solicitado ({total_solicitado:g}) supera el máximo permitido para matrícula {matricula_actual:g}: ${monto_max:,.0f}.",
                        )
            
            # Validar RES-002: HABILITACIÓN <= 10% del total
            if total_habil_resumen is not None and total_solicitado is not None and total_solicitado > 0:
                max_habil = total_solicitado * 0.10
                if total_habil_resumen > (max_habil + 1e-9):
                    _add(
                        findings,
                        SEVERITY_CRITICAL,
                        "RES-002",
                        resumen_sheet,
                        7,
                        "habilitacion",
                        f"Presupuesto de HABILITACIÓN (${total_habil_resumen:,.0f}) supera el 10% del total solicitado (${max_habil:,.0f}). Máximo permitido: ${max_habil:,.0f}.",
                    )
        except Exception as ex:
            _add(findings, SEVERITY_WARNING, "RES-003", resumen_sheet, None, "lectura", f"Error leyendo hoja Resumen: {ex}")

    if innov_sheet:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=innov_sheet, header=None)
            for row_idx in _iter_innovacion_rows(df):
                rows_innov += 1
                row = df.iloc[row_idx]
                
                tipo = _norm_text(row.get(0, ""))
                nombre = _norm_text(row.get(1, ""))
                descripcion = _norm_text(row.get(2, ""))
                oa = _norm_text(row.get(3, ""))
                tipo_innov = _norm_text(row.get(4, ""))
                justificacion = _norm_text(row.get(5, ""))
                cantidad = _to_number(row.get(6))
                valor = _to_number(row.get(7))
                total = _to_number(row.get(8))

                excel_row = row_idx + 1

                required_fields = {
                    "tipo": tipo,
                    "nombre": nombre,
                    "descripcion": descripcion,
                    "objetivo_aprendizaje": oa,
                    "tipo_innovacion": tipo_innov,
                    "justificacion": justificacion,
                }
                for field, value in required_fields.items():
                    if not value:
                        _add(findings, SEVERITY_CRITICAL, "INN-001", innov_sheet, excel_row, field, f"Campo obligatorio vacio: {field}.")

                if tipo_innov and tipo_innov.lower() not in {"profundizar", "complementar"}:
                    _add(findings, SEVERITY_WARNING, "INN-002", innov_sheet, excel_row, "tipo_innovacion", "Tipo de innovacion fuera de catalogo (Profundizar/Complementar).")

                if cantidad is None or cantidad <= 0:
                    _add(findings, SEVERITY_CRITICAL, "INN-003", innov_sheet, excel_row, "cantidad", "Cantidad de innovacion vacia o <= 0.")

                if valor is None or valor <= 0:
                    _add(findings, SEVERITY_CRITICAL, "INN-004", innov_sheet, excel_row, "valor", "Valor unitario de innovacion vacio o <= 0.")

                if cantidad is not None and valor is not None:
                    expected = cantidad * valor
                    if total is not None and abs(expected - total) > 1:
                        _add(findings, SEVERITY_WARNING, "INN-005", innov_sheet, excel_row, "total", "Total de innovacion no coincide con cantidad x valor.")
                    total_innov += expected

                if justificacion and len(justificacion) < 80:
                    _add(findings, SEVERITY_INFO, "INN-006", innov_sheet, excel_row, "justificacion", "Justificacion corta; sugerir revision humana de calidad.")
        except Exception as ex:
            _add(findings, SEVERITY_WARNING, "INN-010", innov_sheet, None, "lectura", f"Error leyendo hoja: {ex}")

    if habil_sheet:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=habil_sheet, header=None)
            if len(df) >= 15 and 4 < len(df.columns):
                habil_val = _to_number(df.iloc[14, 4])
                if habil_val is not None:
                    total_habil = habil_val
        except Exception:
            pass

    total_solicitado_estimado = (total_regular or 0.0) + (total_innov or 0.0) + (total_habil or 0.0)

    if budget_limit is not None and not pd.isna(total_solicitado_estimado) and total_solicitado_estimado > budget_limit:
        _add(findings, SEVERITY_CRITICAL, "BUD-001", "(resumen)", None, "total", "El total solicitado estimado supera el presupuesto maximo configurado.")

    stats = {
        "rbd": rbd_value,
        "especialidad": especialidad_value,
        "rows_regular": rows_regular,
        "rows_innov": rows_innov,
        "rows_eval2": rows_eval2,
        "total_regular_estimado": round(float(total_regular)) if not pd.isna(total_regular) else 0.0,
        "total_innov_estimado": round(float(total_innov)) if not pd.isna(total_innov) else 0.0,
        "total_habil_reportado": round(float(total_habil)) if not pd.isna(total_habil) else 0.0,
        "total_solicitado_estimado": round(float(total_solicitado_estimado)) if not pd.isna(total_solicitado_estimado) else 0.0,
        "critical_count": sum(1 for f in findings if f.severity == SEVERITY_CRITICAL),
        "warning_count": sum(1 for f in findings if f.severity == SEVERITY_WARNING),
        "info_count": sum(1 for f in findings if f.severity == SEVERITY_INFO),
    }

    return ValidationResult(file_name=file_name, sha256=sha256, findings=findings, stats=stats)
