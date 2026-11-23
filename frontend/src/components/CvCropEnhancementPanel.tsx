import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { cvApi } from "../lib/api";
import type { CvEnhancedCropResult, CvEnhancementPreset } from "../lib/types";
import { Alert, Badge, Button, Select } from "./ui";

interface Props {
  caseId: string;
  runId: string;
  observationId: string;
  cropId: string;
}

const DEFAULT_PRESET = "general_enhancement";

function imagePlaceholder(label: string): ReactNode {
  return (
    <div className="grid min-h-[160px] place-items-center rounded border border-dashed border-line bg-black/30 px-3 text-center text-xs text-muted">
      {label}
    </div>
  );
}

export function CvCropEnhancementPanel({ caseId, runId, observationId, cropId }: Props) {
  const [presets, setPresets] = useState<CvEnhancementPreset[]>([]);
  const [preset, setPreset] = useState(DEFAULT_PRESET);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CvEnhancedCropResult | null>(null);
  const [originalFailed, setOriginalFailed] = useState(false);
  const [enhancedFailed, setEnhancedFailed] = useState(false);

  useEffect(() => {
    let mounted = true;
    cvApi.enhancementPresets()
      .then((res) => {
        if (!mounted) return;
        const items = res.items || [];
        setPresets(items);
        if (items.length && !items.some((item) => item.name === DEFAULT_PRESET)) setPreset(items[0].name);
      })
      .catch((e) => { if (mounted) setError(String(e)); })
      .finally(() => { if (mounted) setPresetsLoading(false); });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    setResult(null);
    setError(null);
    setOriginalFailed(false);
    setEnhancedFailed(false);
  }, [caseId, runId, observationId, cropId]);

  const originalUrl = useMemo(() => cvApi.cropUrl(caseId, runId, observationId, cropId), [caseId, runId, observationId, cropId]);
  const enhancedUrl = useMemo(() => {
    if (!result) return null;
    return cvApi.enhancedCropUrl(caseId, runId, observationId, cropId, result.preset);
  }, [caseId, runId, observationId, cropId, result]);

  const runEnhancement = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setEnhancedFailed(false);
    try {
      const res = await cvApi.enhanceCrop({ case_id: caseId, cv_run_id: runId, observation_id: observationId, crop_id: cropId, preset });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const changePreset = (nextPreset: string) => {
    setPreset(nextPreset);
    setResult(null);
    setEnhancedFailed(false);
  };

  return (
    <div className="mt-3 rounded border border-line bg-ink-900 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Image enhancement (derived preview)</p>
        <Badge className="border-warn/30 bg-warn/10 text-warn">AI-enhanced derived image - not original evidence</Badge>
      </div>
      <p className="mt-1 text-[11px] text-muted">Original evidence unchanged. Enhanced output is never used for face matching/embeddings.</p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Select value={preset} onChange={(e) => changePreset(e.target.value)} className="min-w-[220px]" disabled={presetsLoading || !presets.length}>
          {presets.length ? presets.map((p) => <option key={p.name} value={p.name}>{p.label}</option>) : (
            <option value={preset}>{presetsLoading ? "Loading presets…" : "Presets unavailable"}</option>
          )}
        </Select>
        <Button size="sm" variant="primary" loading={loading} disabled={!presets.length} onClick={() => void runEnhancement()}>Enhance</Button>
      </div>

      {error ? <div className="mt-2"><Alert kind="error">{error}</Alert></div> : null}

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-muted">Original</p>
          {originalFailed ? imagePlaceholder("Original crop unavailable") : (
            <img src={originalUrl} alt="Original crop" className="w-full rounded border border-line bg-black" onError={() => setOriginalFailed(true)} />
          )}
        </div>
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-muted">Enhanced {result ? `(${result.preset_label})` : ""}</p>
          {enhancedUrl && !enhancedFailed ? (
            <img src={enhancedUrl} alt="Enhanced crop" className="w-full rounded border border-line bg-black" onError={() => setEnhancedFailed(true)} />
          ) : (
            imagePlaceholder(result ? "Enhanced preview unavailable" : "Run enhancement to generate derived preview")
          )}
        </div>
      </div>

      {result ? (
        <div className="mt-3 grid gap-x-4 gap-y-1 text-[11px] text-slate-300 sm:grid-cols-2">
          <div><span className="text-muted">Preset:</span> {result.preset_label}</div>
          <div><span className="text-muted">Processing:</span> {result.processing_ms.toFixed(2)} ms</div>
          <div><span className="text-muted">Original dims:</span> {result.original_width}x{result.original_height}</div>
          <div><span className="text-muted">Enhanced dims:</span> {result.enhanced_width}x{result.enhanced_height}</div>
          <div className="sm:col-span-2"><span className="text-muted">Original SHA256:</span> <span className="font-mono text-[10px]">{result.original_sha256}</span></div>
          <div className="sm:col-span-2"><span className="text-muted">Enhanced SHA256:</span> <span className="font-mono text-[10px]">{result.enhanced_sha256}</span></div>
          <div className="sm:col-span-2"><span className="text-muted">Method:</span> {result.method} ({result.method_version})</div>
          {result.warnings?.length ? <div className="sm:col-span-2 text-warn">Warnings: {result.warnings.join(", ")}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
