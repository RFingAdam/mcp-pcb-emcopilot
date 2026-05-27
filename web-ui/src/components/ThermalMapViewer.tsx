import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { thermalApi } from '../api/client';

interface ThermalData {
  hotspots: Hotspot[];
  components: ThermalComponent[];
  thermal_vias: ThermalViaGroup[];
  copper_coverage: CopperCoverage[];
  ambient_temp_c: number;
  max_temp_c: number;
  analysis_timestamp: string;
}

interface Hotspot {
  id: string;
  x_mm: number;
  y_mm: number;
  radius_mm: number;
  temperature_c: number;
  severity: 'critical' | 'warning' | 'info';
  contributing_components: string[];
  total_power_w: number;
}

interface ThermalComponent {
  ref: string;
  x_mm: number;
  y_mm: number;
  width_mm: number;
  height_mm: number;
  power_w: number;
  theta_ja: number;
  junction_temp_c: number;
  case_temp_c: number;
  package: string;
}

interface ThermalViaGroup {
  component_ref: string;
  x_mm: number;
  y_mm: number;
  pad_area_mm2: number;
  via_count: number;
  via_drill_mm: number;
  thermal_resistance: number;
  coverage_percent: number;
  recommendation?: string;
}

interface CopperCoverage {
  layer: string;
  total_area_mm2: number;
  copper_area_mm2: number;
  coverage_percent: number;
  heat_spreading_quality: 'excellent' | 'good' | 'fair' | 'poor';
}

const TEMP_COLORS = {
  cold: '#3b82f6',    // Blue - ambient
  cool: '#22c55e',    // Green - safe
  warm: '#eab308',    // Yellow - elevated
  hot: '#f97316',     // Orange - warning
  critical: '#dc2626', // Red - critical
};

function getTemperatureColor(temp: number, maxTemp: number, ambient: number): string {
  const range = maxTemp - ambient;
  const normalized = (temp - ambient) / range;
  
  if (normalized < 0.25) return TEMP_COLORS.cold;
  if (normalized < 0.5) return TEMP_COLORS.cool;
  if (normalized < 0.7) return TEMP_COLORS.warm;
  if (normalized < 0.85) return TEMP_COLORS.hot;
  return TEMP_COLORS.critical;
}

export default function ThermalMapViewer() {
  const { projectId, layoutId } = useParams<{ projectId: string; layoutId: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  const [viewMode, setViewMode] = useState<'heatmap' | 'components' | 'vias' | 'copper'>('heatmap');
  const [showLabels, setShowLabels] = useState(true);
  const [showGrid, setShowGrid] = useState(false);
  const [selectedComponent, setSelectedComponent] = useState<ThermalComponent | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  // Fetch thermal analysis data
  const { data: thermalData, isLoading, error, refetch } = useQuery({
    queryKey: ['thermal-analysis', layoutId],
    queryFn: () => thermalApi.getThermalAnalysis(Number(layoutId)),
    enabled: !!layoutId,
  });

  // Run thermal analysis
  const handleRunAnalysis = async () => {
    await thermalApi.runThermalAnalysis(Number(layoutId));
    refetch();
  };

  // Board dimensions (from thermal data or defaults)
  const boardWidth = 100; // mm
  const boardHeight = 80; // mm

  // Scale factors for canvas
  const scale = useMemo(() => {
    if (!canvasRef.current) return 5;
    const canvas = canvasRef.current;
    return Math.min(canvas.width / boardWidth, canvas.height / boardHeight) * zoom;
  }, [zoom, boardWidth, boardHeight]);

  // Draw thermal map
  useEffect(() => {
    if (!canvasRef.current || !thermalData) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas
    ctx.fillStyle = '#1f2937';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Apply transforms
    ctx.save();
    ctx.translate(pan.x, pan.y);
    ctx.scale(scale, scale);

    // Draw board outline
    ctx.strokeStyle = '#4b5563';
    ctx.lineWidth = 0.5 / scale;
    ctx.strokeRect(0, 0, boardWidth, boardHeight);

    // Draw grid if enabled
    if (showGrid) {
      ctx.strokeStyle = '#374151';
      ctx.lineWidth = 0.1 / scale;
      for (let x = 0; x <= boardWidth; x += 10) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, boardHeight);
        ctx.stroke();
      }
      for (let y = 0; y <= boardHeight; y += 10) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(boardWidth, y);
        ctx.stroke();
      }
    }

    if (viewMode === 'heatmap' || viewMode === 'components') {
      // Draw hotspots as gradients
      thermalData.hotspots.forEach((hotspot: Hotspot) => {
        const gradient = ctx.createRadialGradient(
          hotspot.x_mm, hotspot.y_mm, 0,
          hotspot.x_mm, hotspot.y_mm, hotspot.radius_mm
        );
        const color = getTemperatureColor(
          hotspot.temperature_c,
          thermalData.max_temp_c,
          thermalData.ambient_temp_c
        );
        gradient.addColorStop(0, color + 'cc');
        gradient.addColorStop(1, color + '00');
        
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(hotspot.x_mm, hotspot.y_mm, hotspot.radius_mm, 0, Math.PI * 2);
        ctx.fill();
      });

      // Draw components
      thermalData.components.forEach((comp: ThermalComponent) => {
        const color = getTemperatureColor(
          comp.junction_temp_c,
          thermalData.max_temp_c,
          thermalData.ambient_temp_c
        );
        
        ctx.fillStyle = color + '80';
        ctx.strokeStyle = color;
        ctx.lineWidth = 0.3 / scale;
        
        ctx.fillRect(
          comp.x_mm - comp.width_mm / 2,
          comp.y_mm - comp.height_mm / 2,
          comp.width_mm,
          comp.height_mm
        );
        ctx.strokeRect(
          comp.x_mm - comp.width_mm / 2,
          comp.y_mm - comp.height_mm / 2,
          comp.width_mm,
          comp.height_mm
        );

        // Draw label
        if (showLabels) {
          ctx.fillStyle = '#fff';
          ctx.font = `${1.5 / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(comp.ref, comp.x_mm, comp.y_mm);
          ctx.font = `${1 / scale}px sans-serif`;
          ctx.fillText(`${comp.junction_temp_c.toFixed(0)}°C`, comp.x_mm, comp.y_mm + 2);
        }
      });
    }

    if (viewMode === 'vias') {
      // Draw thermal via groups
      thermalData.thermal_vias.forEach((group: ThermalViaGroup) => {
        const quality = group.coverage_percent > 70 ? '#22c55e' :
                       group.coverage_percent > 40 ? '#eab308' : '#dc2626';
        
        ctx.fillStyle = quality + '60';
        ctx.strokeStyle = quality;
        ctx.lineWidth = 0.3 / scale;
        
        const radius = Math.sqrt(group.pad_area_mm2 / Math.PI);
        ctx.beginPath();
        ctx.arc(group.x_mm, group.y_mm, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Draw individual vias
        const viaRadius = group.via_drill_mm / 2;
        ctx.fillStyle = '#1f2937';
        const viasPerRow = Math.ceil(Math.sqrt(group.via_count));
        const spacing = (radius * 1.5) / viasPerRow;
        
        for (let i = 0; i < group.via_count; i++) {
          const row = Math.floor(i / viasPerRow);
          const col = i % viasPerRow;
          const vx = group.x_mm - radius + spacing * (col + 0.5);
          const vy = group.y_mm - radius + spacing * (row + 0.5);
          
          ctx.beginPath();
          ctx.arc(vx, vy, viaRadius, 0, Math.PI * 2);
          ctx.fill();
        }

        if (showLabels) {
          ctx.fillStyle = '#fff';
          ctx.font = `${1.2 / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(group.component_ref, group.x_mm, group.y_mm - radius - 1);
          ctx.font = `${0.9 / scale}px sans-serif`;
          ctx.fillText(`${group.coverage_percent.toFixed(0)}%`, group.x_mm, group.y_mm);
        }
      });
    }

    ctx.restore();
  }, [thermalData, viewMode, showLabels, showGrid, zoom, pan, scale]);

  // Handle mouse events for component selection
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !thermalData) return;
    
    const rect = canvasRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left - pan.x) / scale;
    const y = (e.clientY - rect.top - pan.y) / scale;

    // Find clicked component
    const clicked = thermalData.components.find((comp: ThermalComponent) => 
      x >= comp.x_mm - comp.width_mm / 2 &&
      x <= comp.x_mm + comp.width_mm / 2 &&
      y >= comp.y_mm - comp.height_mm / 2 &&
      y <= comp.y_mm + comp.height_mm / 2
    );

    setSelectedComponent(clicked || null);
  };

  if (isLoading) {
    return <div className="p-4">Loading thermal analysis...</div>;
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="bg-red-50 text-red-700 p-4 rounded mb-4">
          Error loading thermal data. Please run analysis first.
        </div>
        <button
          onClick={handleRunAnalysis}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Run Thermal Analysis
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <div className="bg-gray-800 border-b border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <Link to={`/projects/${projectId}`} className="text-blue-400 hover:underline text-sm">
              ← Back to Project
            </Link>
            <h1 className="text-2xl font-bold mt-1">Thermal Analysis</h1>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleRunAnalysis}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              🔄 Re-analyze
            </button>
            <button className="px-4 py-2 bg-gray-700 rounded hover:bg-gray-600">
              📥 Export
            </button>
          </div>
        </div>
      </div>

      {/* Stats Bar */}
      {thermalData && (
        <div className="bg-gray-800 px-6 py-3 flex gap-6 text-sm border-b border-gray-700">
          <div>
            <span className="text-gray-400">Ambient:</span>
            <span className="ml-2 font-medium">{thermalData.ambient_temp_c}°C</span>
          </div>
          <div>
            <span className="text-gray-400">Max Temp:</span>
            <span className="ml-2 font-medium text-red-400">{thermalData.max_temp_c.toFixed(1)}°C</span>
          </div>
          <div>
            <span className="text-gray-400">Hotspots:</span>
            <span className="ml-2 font-medium">{thermalData.hotspots.length}</span>
          </div>
          <div>
            <span className="text-gray-400">Components:</span>
            <span className="ml-2 font-medium">{thermalData.components.length}</span>
          </div>
        </div>
      )}

      <div className="flex">
        {/* Toolbar */}
        <div className="w-64 bg-gray-800 border-r border-gray-700 p-4">
          {/* View Mode */}
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2 text-gray-300">View Mode</label>
            <div className="space-y-1">
              {[
                { id: 'heatmap', label: '🌡️ Heat Map', desc: 'Temperature distribution' },
                { id: 'components', label: '📦 Components', desc: 'Power dissipation' },
                { id: 'vias', label: '🔩 Thermal Vias', desc: 'Via coverage analysis' },
                { id: 'copper', label: '🟫 Copper', desc: 'Heat spreading' },
              ].map((mode) => (
                <button
                  key={mode.id}
                  onClick={() => setViewMode(mode.id as any)}
                  className={`w-full text-left px-3 py-2 rounded ${
                    viewMode === mode.id ? 'bg-blue-600' : 'bg-gray-700 hover:bg-gray-600'
                  }`}
                >
                  <div className="font-medium">{mode.label}</div>
                  <div className="text-xs text-gray-400">{mode.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Display Options */}
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2 text-gray-300">Display</label>
            <label className="flex items-center gap-2 mb-2">
              <input
                type="checkbox"
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
              />
              <span>Show Labels</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={showGrid}
                onChange={(e) => setShowGrid(e.target.checked)}
              />
              <span>Show Grid</span>
            </label>
          </div>

          {/* Zoom */}
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2 text-gray-300">Zoom</label>
            <input
              type="range"
              min="0.5"
              max="3"
              step="0.1"
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              className="w-full"
            />
            <div className="text-center text-sm text-gray-400">{(zoom * 100).toFixed(0)}%</div>
          </div>

          {/* Temperature Legend */}
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2 text-gray-300">Temperature</label>
            <div className="h-4 rounded flex overflow-hidden">
              <div className="flex-1" style={{ backgroundColor: TEMP_COLORS.cold }}></div>
              <div className="flex-1" style={{ backgroundColor: TEMP_COLORS.cool }}></div>
              <div className="flex-1" style={{ backgroundColor: TEMP_COLORS.warm }}></div>
              <div className="flex-1" style={{ backgroundColor: TEMP_COLORS.hot }}></div>
              <div className="flex-1" style={{ backgroundColor: TEMP_COLORS.critical }}></div>
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>{thermalData?.ambient_temp_c || 25}°C</span>
              <span>{thermalData?.max_temp_c || 100}°C</span>
            </div>
          </div>

          {/* Hotspots List */}
          {thermalData && thermalData.hotspots.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-2 text-gray-300">Hotspots</label>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {thermalData.hotspots.map((hs: Hotspot) => (
                  <div
                    key={hs.id}
                    className="bg-gray-700 rounded p-2 text-sm cursor-pointer hover:bg-gray-600"
                  >
                    <div className="flex justify-between">
                      <span className={
                        hs.severity === 'critical' ? 'text-red-400' :
                        hs.severity === 'warning' ? 'text-yellow-400' : 'text-blue-400'
                      }>
                        {hs.severity === 'critical' ? '🔴' : hs.severity === 'warning' ? '🟡' : '🔵'}
                        {' '}{hs.temperature_c.toFixed(1)}°C
                      </span>
                      <span className="text-gray-400">{hs.total_power_w.toFixed(1)}W</span>
                    </div>
                    <div className="text-xs text-gray-400 mt-1">
                      {hs.contributing_components.join(', ')}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Canvas */}
        <div className="flex-1 p-4">
          <canvas
            ref={canvasRef}
            width={800}
            height={600}
            onClick={handleCanvasClick}
            className="border border-gray-700 rounded cursor-crosshair"
          />
        </div>

        {/* Component Detail Panel */}
        {selectedComponent && (
          <div className="w-80 bg-gray-800 border-l border-gray-700 p-4">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-semibold">{selectedComponent.ref}</h3>
              <button
                onClick={() => setSelectedComponent(null)}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-400">Package</label>
                <div>{selectedComponent.package}</div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-gray-400">Power</label>
                  <div className="text-lg font-medium">{selectedComponent.power_w.toFixed(2)} W</div>
                </div>
                <div>
                  <label className="text-xs text-gray-400">θJA</label>
                  <div className="text-lg font-medium">{selectedComponent.theta_ja} °C/W</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-gray-400">Junction Temp</label>
                  <div className={`text-lg font-medium ${
                    selectedComponent.junction_temp_c > 100 ? 'text-red-400' :
                    selectedComponent.junction_temp_c > 80 ? 'text-yellow-400' : 'text-green-400'
                  }`}>
                    {selectedComponent.junction_temp_c.toFixed(1)} °C
                  </div>
                </div>
                <div>
                  <label className="text-xs text-gray-400">Case Temp</label>
                  <div className="text-lg font-medium">
                    {selectedComponent.case_temp_c.toFixed(1)} °C
                  </div>
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-400">Size</label>
                <div>{selectedComponent.width_mm} × {selectedComponent.height_mm} mm</div>
              </div>

              <div>
                <label className="text-xs text-gray-400">Position</label>
                <div>({selectedComponent.x_mm.toFixed(1)}, {selectedComponent.y_mm.toFixed(1)}) mm</div>
              </div>

              {/* Thermal Recommendations */}
              <div className="border-t border-gray-700 pt-4">
                <label className="text-xs text-gray-400">Recommendations</label>
                <ul className="text-sm space-y-2 mt-2">
                  {selectedComponent.junction_temp_c > 100 && (
                    <li className="text-red-400">⚠️ Junction temp exceeds 100°C - add cooling</li>
                  )}
                  {selectedComponent.power_w > 2 && (
                    <li className="text-yellow-400">💡 Consider thermal vias under pad</li>
                  )}
                  {selectedComponent.theta_ja > 40 && (
                    <li className="text-blue-400">ℹ️ High θJA - ensure adequate copper area</li>
                  )}
                </ul>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Copper Coverage Table */}
      {viewMode === 'copper' && thermalData && (
        <div className="bg-gray-800 border-t border-gray-700 p-4">
          <h3 className="font-semibold mb-3">Copper Coverage by Layer</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400">
                <th className="text-left py-2">Layer</th>
                <th className="text-right py-2">Total Area</th>
                <th className="text-right py-2">Copper Area</th>
                <th className="text-right py-2">Coverage</th>
                <th className="text-left py-2 pl-4">Quality</th>
              </tr>
            </thead>
            <tbody>
              {thermalData.copper_coverage.map((layer: CopperCoverage) => (
                <tr key={layer.layer} className="border-t border-gray-700">
                  <td className="py-2">{layer.layer}</td>
                  <td className="text-right">{layer.total_area_mm2.toFixed(1)} mm²</td>
                  <td className="text-right">{layer.copper_area_mm2.toFixed(1)} mm²</td>
                  <td className="text-right">{layer.coverage_percent.toFixed(1)}%</td>
                  <td className={`pl-4 ${
                    layer.heat_spreading_quality === 'excellent' ? 'text-green-400' :
                    layer.heat_spreading_quality === 'good' ? 'text-blue-400' :
                    layer.heat_spreading_quality === 'fair' ? 'text-yellow-400' : 'text-red-400'
                  }`}>
                    {layer.heat_spreading_quality}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
