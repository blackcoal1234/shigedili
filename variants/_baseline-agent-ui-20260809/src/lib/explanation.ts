import type {
  ImageryPayload,
  RoutePayload,
  ScenePayload,
  WorkbenchMode,
  WorkbenchPayload,
} from "@/lib/types";

export interface ExplanationModel {
  title: string;
  metric: string;
  metricLabel: string;
  notes: [string, string];
  points: Array<{ label: string; value: number }>;
}

function routeExplanation(payload: RoutePayload): ExplanationModel {
  const points = payload.scenes.slice(0, 6).map((scene, index) => ({
    label: scene.year_label,
    value: payload.sceneCount <= 1 ? 0 : index / Math.min(payload.sceneCount - 1, 5),
  }));
  return {
    title: `${payload.poet}行迹证据摘要`,
    metric: `${payload.mappedSceneCount}/${payload.sceneCount}`,
    metricLabel: "可落图镜头",
    notes: [
      `${payload.dynasty} · 语料 ${payload.corpusWorkCount} 篇`,
      `时间精度 ${Object.keys(payload.precisionCounts ?? {}).length} 类`,
    ],
    points,
  };
}

function sceneExplanation(payload: ScenePayload): ExplanationModel {
  const first = payload.scenes[0];
  const last = payload.scenes.at(-1);
  return {
    title: `${payload.poet}逐幕结构摘要`,
    metric: String(payload.sceneCount),
    metricLabel: "史料镜头",
    notes: [
      `${first?.year_label ?? "未系年"} 至 ${last?.year_label ?? "未系年"}`,
      payload.pauseAtEachScene === false ? "连续播放配置" : "默认逐幕停驻",
    ],
    points: payload.scenes.slice(0, 6).map((scene, index) => ({
      label: scene.year_label,
      value: payload.sceneCount <= 1 ? 0 : index / Math.min(payload.sceneCount - 1, 5),
    })),
  };
}

function imageryExplanation(payload: ImageryPayload): ExplanationModel {
  const max = Math.max(
    1,
    ...payload.comparisons.flatMap((row) => [row.tang.ratePer10k, row.song.ratePer10k]),
  );
  return {
    title: "唐宋意象率差摘要",
    metric: String(payload.comparisons.length),
    metricLabel: "审核意象词",
    notes: [
      "统一按每万汉字归一化",
      `词表范围 ${payload.allowedTermCount} 词`,
    ],
    points: payload.comparisons.slice(0, 6).map((row) => ({
      label: row.word,
      value: Math.max(row.tang.ratePer10k, row.song.ratePer10k) / max,
    })),
  };
}

export function createExplanationModel(
  mode: WorkbenchMode,
  payload: WorkbenchPayload,
): ExplanationModel {
  if (mode === "imagery") {
    return imageryExplanation(payload as ImageryPayload);
  }
  if (mode === "scenes") {
    return sceneExplanation(payload as ScenePayload);
  }
  return routeExplanation(payload as RoutePayload);
}
