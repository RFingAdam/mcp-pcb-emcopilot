import React from 'react';
import type { LayerVisibility } from './PCBViewer';

interface LayerControlsProps {
  visibility: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  availableLayers: string[];
}

const LAYER_INFO: Record<keyof LayerVisibility, { label: string; color: string }> = {
  top: { label: 'Top Copper', color: '#ff4444' },
  bottom: { label: 'Bottom Copper', color: '#4444ff' },
  soldermask_top: { label: 'Top Soldermask', color: '#00aa00' },
  soldermask_bottom: { label: 'Bottom Soldermask', color: '#00aa00' },
  silkscreen_top: { label: 'Top Silkscreen', color: '#ffffff' },
  silkscreen_bottom: { label: 'Bottom Silkscreen', color: '#ffff00' },
  drill: { label: 'Drill Holes', color: '#666666' },
  outline: { label: 'Board Outline', color: '#ffffff' },
};

export default function LayerControls({
  visibility,
  onToggle,
  availableLayers,
}: LayerControlsProps) {
  return (
    <div className="w-48 bg-gray-800 border-r border-gray-700 p-3 overflow-y-auto">
      <h4 className="text-gray-400 text-xs uppercase tracking-wider mb-3">Layers</h4>

      <div className="space-y-1">
        {(Object.keys(LAYER_INFO) as Array<keyof LayerVisibility>).map(layer => {
          const info = LAYER_INFO[layer];
          const isAvailable = availableLayers.some(
            l => l === layer || l.includes(layer.replace('_', ''))
          ) || ['outline', 'drill'].includes(layer);

          return (
            <button
              key={layer}
              onClick={() => onToggle(layer)}
              disabled={!isAvailable}
              className={`
                w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-left
                transition-colors
                ${visibility[layer]
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-400 hover:bg-gray-700/50'}
                ${!isAvailable ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'}
              `}
            >
              <span
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{
                  backgroundColor: visibility[layer] ? info.color : 'transparent',
                  border: `2px solid ${info.color}`,
                }}
              />
              <span className="truncate">{info.label}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-4 pt-4 border-t border-gray-700">
        <h4 className="text-gray-400 text-xs uppercase tracking-wider mb-2">Quick Select</h4>
        <div className="flex gap-2">
          <button
            onClick={() => {
              Object.keys(visibility).forEach(layer => {
                if (!visibility[layer as keyof LayerVisibility]) {
                  onToggle(layer as keyof LayerVisibility);
                }
              });
            }}
            className="flex-1 px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600"
          >
            All On
          </button>
          <button
            onClick={() => {
              Object.keys(visibility).forEach(layer => {
                if (visibility[layer as keyof LayerVisibility]) {
                  onToggle(layer as keyof LayerVisibility);
                }
              });
            }}
            className="flex-1 px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600"
          >
            All Off
          </button>
        </div>
      </div>
    </div>
  );
}
