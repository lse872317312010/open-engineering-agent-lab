"""Build an offline interactive validation-point magnetic-map report with Plotly."""
import argparse
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sidecar = args.output.with_suffix(args.output.suffix + ".json")
    if args.output.exists() or sidecar.exists():
        raise ValueError("output HTML and evidence sidecar must not already exist")
    source = args.fit_dir / "validation-predictions.npz"
    summary_path = args.fit_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    with np.load(source, allow_pickle=False) as data:
        current = np.asarray(data["current_dq"]).flatten()
        flux = np.asarray(data["flux_dq"]).flatten()
        pred_i = np.asarray(data["predicted_current_dq"]).flatten()
        pred_psi = np.asarray(data["predicted_flux_dq"]).flatten()
    vectors = (current, flux, pred_i, pred_psi)
    if (len(current) == 0 or any(v.shape != current.shape for v in vectors)
            or not all(np.isfinite(v).all() and np.iscomplexobj(v) for v in vectors)):
        raise ValueError("validation point arrays must be finite, complex and aligned")

    def view(input_dq, target, prediction, axis, input_unit, output_unit):
        observed = target.real if axis == "d" else target.imag
        predicted = prediction.real if axis == "d" else prediction.imag
        return {"x": input_dq.real, "y": input_dq.imag, "observed": observed,
                "predicted": predicted, "component_error": np.abs(predicted - observed),
                "vector_error": np.abs(prediction - target),
                "input_unit": input_unit, "output_unit": output_unit}

    views = {
        "磁链 d": view(current, flux, pred_psi, "d", "A peak", "Wb"),
        "磁链 q": view(current, flux, pred_psi, "q", "A peak", "Wb"),
        "电流 d": view(flux, current, pred_i, "d", "Wb", "A peak"),
        "电流 q": view(flux, current, pred_i, "q", "Wb", "A peak"),
    }
    initial = views["磁链 d"]
    fig = make_subplots(rows=2, cols=2, subplot_titles=(
        "源数据", "模型预测", "分量绝对误差", "dq 向量误差"
    ))
    for row, col, key, coloraxis in ((1, 1, "observed", "coloraxis"),
                                      (1, 2, "predicted", "coloraxis"),
                                      (2, 1, "component_error", "coloraxis2"),
                                      (2, 2, "vector_error", "coloraxis3")):
        fig.add_trace(go.Scattergl(
            x=initial["x"], y=initial["y"], mode="markers",
            marker={"size": 8, "color": initial[key], "coloraxis": coloraxis},
            hovertemplate="d=%{x:.5g}<br>q=%{y:.5g}<br>数值=%{marker.color:.5g}<extra></extra>",
            showlegend=False,
        ), row=row, col=col)
    buttons = []
    for label, data in views.items():
        colors = [data["observed"], data["predicted"], data["component_error"],
                  data["vector_error"]]
        axis_updates = {}
        for axis in ("xaxis", "xaxis2", "xaxis3", "xaxis4"):
            axis_updates[axis + ".title.text"] = "d 输入 (" + data["input_unit"] + ")"
        for axis in ("yaxis", "yaxis2", "yaxis3", "yaxis4"):
            axis_updates[axis + ".title.text"] = "q 输入 (" + data["input_unit"] + ")"
        for axis in ("coloraxis", "coloraxis2", "coloraxis3"):
            axis_updates[axis + ".colorbar.title.text"] = data["output_unit"]
        buttons.append({"label": label, "method": "update",
                        "args": [{"x": [data["x"]] * 4, "y": [data["y"]] * 4,
                                  "marker.color": colors}, axis_updates]})
    for row in (1, 2):
        for col in (1, 2):
            fig.update_xaxes(title_text="d 输入 (A peak)", row=row, col=col)
            fig.update_yaxes(title_text="q 输入 (A peak)", row=row, col=col)
    fig.update_layout(
        template="plotly_white", height=850, title={"text": "电机磁图验证点 · 交互报告"},
        margin={"t": 150, "b": 65},
        updatemenus=[{"buttons": buttons, "direction": "right", "x": 0, "y": 1.13}],
        coloraxis={"colorscale": "Viridis", "colorbar": {"title": "Wb", "x": 0.46, "len": 0.38,
                                                            "y": 0.80}},
        coloraxis2={"colorscale": "Magma", "colorbar": {"title": "Wb", "x": 0.46, "len": 0.38,
                                                           "y": 0.22}},
        coloraxis3={"colorscale": "Magma", "colorbar": {"title": "Wb", "x": 1.02, "len": 0.38,
                                                           "y": 0.22}},
    )
    fig.add_annotation(
        text="仅显示验证数据点；模型有效域、独立物理精度和控制性能未由此图证明。",
        x=0, y=1.07, xref="paper", yref="paper", showarrow=False, align="left"
    )
    validation = summary["results"]["validation"]
    flux_rmse = float(validation["flux_error_wb"]["rmse"])
    current_rmse = float(validation["current_error_a"]["rmse"])
    if not np.isfinite([flux_rmse, current_rmse]).all():
        raise ValueError("validation metrics must be finite")
    fig.add_annotation(
        text=(f"验证点 {len(current)} · 磁链 RMSE {flux_rmse:.4g} Wb"
              f" · 电流 RMSE {current_rmse:.4g} A"),
        x=0, y=1.02, xref="paper", yref="paper", showarrow=False, align="left"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(args.output), include_plotlyjs=True, full_html=True)
    evidence = {
        "validation_predictions_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "fit_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "output_html_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "points": len(current), "fit_validation": summary["results"]["validation"],
        "versions": {"plotly": version("plotly"), "numpy": version("numpy")},
        "limitations": ["validation points only; no continuous validity or physical proof",
                        "user must keep source data and independent final holdout"],
    }
    sidecar.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
