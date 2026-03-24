from __future__ import annotations

import hashlib
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from src.validator import ValidationResult, RULE_DESCRIPTIONS, validate_workbook


# Usar /tmp en Streamlit Cloud, data/uploads en desarrollo local
if "STREAMLIT_SERVER_HEADLESS" in os.environ:
    UPLOAD_DIR = Path("/tmp/streamlit_uploads")
else:
    UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _build_excel(summary_df: pd.DataFrame, details_df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Resumen", index=False)
        details_df.to_excel(writer, sheet_name="Observaciones", index=False)
    return buf.getvalue()


def _store_original(file_name: str, content: bytes, sha256: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    out_name = f"{timestamp}_{sha256[:12]}_{safe_name}"
    out_path = UPLOAD_DIR / out_name
    out_path.write_bytes(content)
    return out_path


def _build_classified_zip(summary_rows: list[dict]) -> bytes:
    """Genera un ZIP con dos carpetas: inadmisibles/ y ok/."""
    buffer = BytesIO()
    used_names: dict[str, int] = {}

    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zf:
        for row in summary_rows:
            stored_path_str = row.get("almacenado_en")
            if not stored_path_str:
                continue

            stored_path = Path(stored_path_str)
            if not stored_path.exists():
                continue

            critical_count = int(row.get("Críticos") or 0)
            folder = "inadmisibles" if critical_count > 0 else "ok"

            original_name = str(row.get("Archivo") or stored_path.name).replace("/", "_").replace("\\", "_")
            count = used_names.get(original_name, 0)
            used_names[original_name] = count + 1
            if count > 0:
                stem = Path(original_name).stem
                suffix = Path(original_name).suffix
                zip_name = f"{stem}_{count}{suffix}"
            else:
                zip_name = original_name

            zf.write(stored_path, arcname=f"{folder}/{zip_name}")

    buffer.seek(0)
    return buffer.getvalue()


def _result_to_rows(result: ValidationResult) -> list[dict]:
    rows = []
    rbd = result.stats.get("rbd", "")
    especialidad = result.stats.get("especialidad", "")
    for f in result.findings:
        # Obtener descripción amigable de la regla
        rule_desc = RULE_DESCRIPTIONS.get(f.rule_id, f.rule_id)
        rows.append(
            {
                "Archivo": result.file_name,
                "RBD": rbd,
                "Especialidad": especialidad,
                "Severidad": f.severity,
                "Regla": f.rule_id,
                "Descripción": rule_desc,
                "Hoja": f.sheet,
                "Fila": f.row,
                "Campo": f.field,
                "Detalle": f.message,
            }
        )
    return rows


def _summary_row(result: ValidationResult) -> dict:
    stats = result.stats
    estado = "✅ OK"
    if stats["critical_count"] > 0:
        estado = "🔴 CRÍTICO"
    elif stats["warning_count"] > 0:
        estado = "⚠️ REVISAR"

    return {
        "Archivo": result.file_name,
        "RBD": stats.get("rbd", ""),
        "Especialidad": stats.get("especialidad", ""),
        "Estado": estado,
        "Críticos": stats["critical_count"],
        "Advertencias": stats["warning_count"],
        "Info": stats["info_count"],
        "Filas Equipamiento": stats["rows_regular"],
        "Filas Innovación": stats["rows_innov"],
        "Total Regular": f"${stats['total_regular_estimado']:,.0f}",
        "Total Innovación": f"${stats['total_innov_estimado']:,.0f}",
        "Total Habilitación": f"${stats['total_habil_reportado']:,.0f}",
        "Total Solicitado": f"${stats['total_solicitado_estimado']:,.0f}",
    }


def main() -> None:
    st.set_page_config(page_title="Beta Revision EMTP", layout="wide")
    st.title("🎓 Beta Local - Revisión de Planillas EMTP")
    st.markdown("**Sistema de validación automática de planillas de Equipamiento para establecimientos EMTP**")
    st.markdown("---")

    with st.sidebar:
        st.header("⚙️ Configuración")
        st.markdown("**sobre esta aplicación:**")
        st.info(
            "📌 **SHA256:** Identificador único (huella digital) de cada archivo para garantizar trazabilidad e inmutabilidad. "
            "Si un archivo se modifica, su SHA256 cambia."
        )
        st.divider()
        
        # Diccionario de reglas en sidebar
        with st.expander("📚 Diccionario de Todas las Reglas", expanded=False):
            # Organizar reglas por categoría
            categories = {
                "Estructura": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("STR-")},
                "Especialidad": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("ESP-")},
                "Evaluación 1": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("EV1-")},
                "Evaluación 2": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("EV2-")},
                "Innovación": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("INN-")},
                "Resumen": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("RES-")},
                "Presupuesto": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("BUD-")},
                "Sistema": {k: v for k, v in RULE_DESCRIPTIONS.items() if k.startswith("SYS-")},
            }
            
            # Crear tabs para cada categoría
            tabs = st.tabs([cat for cat, rules in categories.items() if rules])
            for (category, rules), tab in zip([(k, v) for k, v in categories.items() if v], tabs):
                with tab:
                    for rule_id, description in sorted(rules.items()):
                        st.markdown(f"**{rule_id}** — {description}")

    files = st.file_uploader(
        "📂 Sube una o más planillas .xlsx",
        type=["xlsx"],
        accept_multiple_files=True,
    )

    if not files:
        st.info("👉 Carga uno o varios archivos .xlsx para validar. Los originales se preservan inmutables.")
        return

    if st.button("▶️ Procesar planillas", type="primary"):
        summary_rows: list[dict] = []
        detail_rows: list[dict] = []

        progress = st.progress(0)
        status = st.empty()

        for i, f in enumerate(files, start=1):
            status.write(f"Procesando {f.name} ({i}/{len(files)})")
            content = f.read()
            sha256 = _sha256_bytes(content)
            stored_path = _store_original(f.name, content, sha256)

            try:
                result = validate_workbook(
                    file_name=f.name,
                    file_bytes=content,
                    sha256=sha256,
                )
            except Exception as ex:  # noqa: BLE001
                summary_rows.append(
                    {
                        "Archivo": f.name,
                        "RBD": "",
                        "Especialidad": "",
                        "Estado": "🚫 ERROR",
                        "Críticos": 1,
                        "Advertencias": 0,
                        "Info": 0,
                        "Filas Equipamiento": None,
                        "Filas Innovación": None,
                        "Total Regular": "$0",
                        "Total Innovación": "$0",
                        "Total Habilitación": "$0",
                        "Total Solicitado": "$0",
                        "almacenado_en": str(stored_path),
                    }
                )
                detail_rows.append(
                    {
                        "Archivo": f.name,
                        "RBD": "",
                        "Especialidad": "",
                        "Severidad": "Crítico",
                        "Regla": "SYS-001",
                        "Descripción": "Error procesando archivo",
                        "Hoja": "(workbook)",
                        "Fila": None,
                        "Campo": "archivo",
                        "Detalle": f"Error: {ex}",
                    }
                )
            else:
                row = _summary_row(result)
                row["almacenado_en"] = str(stored_path)
                summary_rows.append(row)
                detail_rows.extend(_result_to_rows(result))

            progress.progress(i / len(files))

        status.write("Proceso finalizado.")

        summary_df = pd.DataFrame(summary_rows)
        details_df = pd.DataFrame(detail_rows)

        st.subheader("📊 Resumen por Archivo")
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        st.subheader("📋 Observaciones Detalladas")
        if details_df.empty:
            st.success("✅ No se detectaron observaciones con las reglas activas.")
        else:
            # Agregar diccionario de reglas encontradas
            with st.expander("📖 ¿Qué significa cada código de regla?", expanded=False):
                st.markdown("**Diccionario de Reglas Encontradas:**")
                
                # Extraer reglas únicas y mostrar con descripción
                unique_rules = details_df["Regla"].unique()
                rules_dict = {}
                for rule_id in sorted(unique_rules):
                    if rule_id in RULE_DESCRIPTIONS:
                        rules_dict[rule_id] = RULE_DESCRIPTIONS[rule_id]
                    else:
                        rules_dict[rule_id] = "(sin descripción disponible)"
                
                # Mostrar en columnas para mejor визуальización
                cols_per_row = 2
                for i in range(0, len(rules_dict), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for j, (rule_id, description) in enumerate(list(rules_dict.items())[i : i + cols_per_row]):
                        with cols[j]:
                            st.markdown(f"**{rule_id}**")
                            st.write(f"{description}")
            
            st.dataframe(details_df, use_container_width=True, hide_index=True)

        classified_zip = _build_classified_zip(summary_rows)

        excel_bytes = _build_excel(summary_df, details_df)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                label="📥 Descargar Resultados (Excel)",
                data=excel_bytes,
                file_name="resultados_validacion_emtp.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Contiene dos hojas: Resumen y Observaciones.",
            )

        with col2:
            obs_buf = BytesIO()
            with pd.ExcelWriter(obs_buf, engine="openpyxl") as writer:
                details_df.to_excel(writer, sheet_name="Observaciones", index=False)
            st.download_button(
                label="📋 Descargar solo Observaciones (Excel)",
                data=obs_buf.getvalue(),
                file_name="observaciones_validacion_emtp.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Solo la hoja de observaciones detalladas.",
            )

        with col3:
            st.download_button(
                label="📦 Descargar archivos clasificados (ZIP)",
                data=classified_zip,
                file_name="planillas_clasificadas_emtp.zip",
                mime="application/zip",
                help="Incluye dos carpetas: inadmisibles/ (con críticos) y ok/ (sin críticos).",
            )


if __name__ == "__main__":
    main()
