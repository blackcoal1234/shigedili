"use client";

import { SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type {
  EffectiveMotionProfile,
  MotionPreference,
  MotionProfile,
} from "@/lib/motion";

const PROFILE_OPTIONS: Array<{
  id: MotionProfile;
  label: string;
  description: string;
}> = [
  { id: "restrained", label: "克制", description: "轻量过渡，信息优先" },
  { id: "cinematic", label: "电影", description: "完整镜头与纸本转场" },
  { id: "experimental", label: "实验", description: "强化墨迹、景深与潮汐" },
];

interface MotionLabControlsProps {
  preference: MotionPreference;
  effectiveProfile: EffectiveMotionProfile;
  onChange: (preference: MotionPreference) => void;
}

export function MotionLabControls({
  preference,
  effectiveProfile,
  onChange,
}: MotionLabControlsProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (wasOpenRef.current && !open) triggerRef.current?.focus();
    wasOpenRef.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  return (
    <div className="motion-lab-controls">
      <button
        type="button"
        className="motion-lab-trigger"
        data-motion-lab-control="agent-ui-motion-lab"
        ref={triggerRef}
        aria-expanded={open}
        aria-controls="motion-lab-panel"
        onClick={() => setOpen((current) => !current)}
      >
        <SlidersHorizontal size={16} aria-hidden="true" />
        <span>动画实验室</span>
        <i data-profile={effectiveProfile} aria-hidden="true" />
      </button>

      {open ? (
        <section id="motion-lab-panel" className="motion-lab-panel" aria-label="动画实验室设置">
          <header>
            <div>
              <span>Tweaks</span>
              <strong>动画实验室</strong>
            </div>
            <button type="button" aria-label="关闭动画实验室" onClick={() => setOpen(false)}>
              <X size={17} aria-hidden="true" />
            </button>
          </header>

          <label className="motion-master-toggle">
            <span>
              <strong>动画总开关</strong>
              <small>{effectiveProfile === "off" ? "关闭动画 · 当前静态展示" : "不改变任何史料或数值"}</small>
            </span>
            <input
              type="checkbox"
              aria-label={preference.enabled ? "关闭动画" : "启用复杂动画"}
              checked={preference.enabled}
              onChange={(event) => onChange({ ...preference, enabled: event.target.checked })}
            />
            <i aria-hidden="true"><b /></i>
          </label>

          <fieldset disabled={!preference.enabled}>
            <legend>动效风格</legend>
            <div className="motion-profile-options">
              {PROFILE_OPTIONS.map((option) => (
                <button
                  type="button"
                  key={option.id}
                  data-active={preference.profile === option.id}
                  aria-pressed={preference.profile === option.id}
                  onClick={() => onChange({ ...preference, profile: option.id })}
                >
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </button>
              ))}
            </div>
          </fieldset>

          <p className="motion-reduced-note">
            系统开启“减少动态效果”时，本页会自动切换为静态展示。
          </p>
        </section>
      ) : null}
    </div>
  );
}
