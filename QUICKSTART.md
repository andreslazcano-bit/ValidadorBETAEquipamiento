## 🚀 BETA LOCAL - Revision EMTP | Inicio Rápido

### 1. Instalar dependencias (una sola vez)
```bash
cd beta_revision_emtp
pip install -r requirements.txt
```

### 2. Ejecutar la app
```bash
cd beta_revision_emtp
streamlit run app.py
```

### 3. Abrir navegador
Automáticamente se abrirá en `http://localhost:8501`

---

## ¿Qué hace?

1. **Subir**: Puedes arrastrar múltiples Excel (.xlsx) sin editar
2. **Validar**: La app revisa 30+ criterios automaticamente
3. **Ver resultados**: 
   - Tabla resumen (estado, cantidad de alertas, totales)
   - Tabla detallada (hoja, fila, regla incumplida)
4. **Descargar**: Exporta todo a CSV para auditoría

---

## Originales seguros

Cada planilla se guarda intacta en `data/uploads/` con fecha+hash.

---

## Prueba rápida sin UI

```bash
cd beta_revision_emtp
python test_validator.py
```

Te muestra: criticos, advertencias, filas, totales detectados.

---

## Próximos pasos

- Ampliar reglas según feedback.
- Agregar soporte de IA para justificaciones.
- Integración con dashboard.

¡Listo para probar!
