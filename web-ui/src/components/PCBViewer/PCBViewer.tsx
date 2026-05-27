import React, { useState, useCallback } from 'react';
import PCBCanvas from './PCBCanvas';
import LayerControls from './LayerControls';
import ViewControls from './ViewControls';

export interface LayerVisibility {
  top: boolean;
  bottom: boolean;
  soldermask_top: boolean;
  soldermask_bottom: boolean;
  silkscreen_top: boolean;
  silkscreen_bottom: boolean;
  drill: boolean;
  outline: boolean;
}

export interface PCBData {
  board_width_mm: number;
  board_height_mm: number;
  layers: {
    name: string;
    type: string;
    features: Feature[];
  }[];
  violations?: Violation[];
}

export interface Feature {
  type: 'trace' | 'pad' | 'via' | 'region' | 'arc';
  points: { x: number; y: number }[];
  width?: number;
  layer: string;
  net?: string;
}

export interface Violation {
  id: string;
  type: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  location: { x: number; y: number };
  affected_features?: string[];
  net_name?: string;  // Net associated with this violation
}

interface PCBViewerProps {
  data: PCBData | null;
  onViolationClick?: (violation: Violation) => void;
  selectedViolation?: string | null;
  className?: string;
}

const defaultLayerVisibility: LayerVisibility = {
  top: true,
  bottom: true,
  soldermask_top: false,
  soldermask_bottom: false,
  silkscreen_top: true,
  silkscreen_bottom: false,
  drill: true,
  outline: true,
};

export default function PCBViewer({
  data,
  onViolationClick,
  selectedViolation,
  className = '',
}: PCBViewerProps) {
  const [layerVisibility, setLayerVisibility] = useState<LayerVisibility>(defaultLayerVisibility);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [measureMode, setMeasureMode] = useState(false);
  const [highlightedNet, setHighlightedNet] = useState<string | null>(null);

  // Update highlighted net when violation is selected
  React.useEffect(() => {
    if (selectedViolation && data?.violations) {
      const violation = data.violations.find(v => v.id === selectedViolation);
      setHighlightedNet(violation?.net_name || null);
    } else {
      setHighlightedNet(null);
    }
  }, [selectedViolation, data?.violations]);

  const handleLayerToggle = useCallback((layer: keyof LayerVisibility) => {
    setLayerVisibility(prev => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const handleZoomIn = useCallback(() => {
    setZoom(prev => Math.min(prev * 1.25, 10));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom(prev => Math.max(prev / 1.25, 0.1));
  }, []);

  const handleZoomFit = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const handlePanChange = useCallback((newPan: { x: number; y: number }) => {
    setPan(newPan);
  }, []);

  if (!data) {
    return (
      <div className={`flex items-center justify-center bg-gray-100 rounded-lg ${className}`}>
        <p className="text-gray-500">No PCB data loaded</p>
      </div>
    );
  }

  return (
    <div className={`flex flex-col bg-gray-900 rounded-lg overflow-hidden ${className}`}>
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-4">
          <h3 className="text-white font-medium">PCB Viewer</h3>
          <span className="text-gray-400 text-sm">
            {data.board_width_mm.toFixed(1)} x {data.board_height_mm.toFixed(1)} mm
          </span>
        </div>
        <ViewControls
          zoom={zoom}
          onZoomIn={handleZoomIn}
          onZoomOut={handleZoomOut}
          onZoomFit={handleZoomFit}
          measureMode={measureMode}
          onMeasureToggle={() => setMeasureMode(!measureMode)}
        />
      </div>

      <div className="flex flex-1 min-h-0">
        <LayerControls
          visibility={layerVisibility}
          onToggle={handleLayerToggle}
          availableLayers={data.layers.map(l => l.name)}
        />

        <div className="flex-1 relative">
          <PCBCanvas
            data={data}
            layerVisibility={layerVisibility}
            zoom={zoom}
            pan={pan}
            onPanChange={handlePanChange}
            measureMode={measureMode}
            selectedViolation={selectedViolation}
            onViolationClick={onViolationClick}
            highlightedNet={highlightedNet}
            onNetHover={setHighlightedNet}
          />
        </div>
      </div>
    </div>
  );
}
