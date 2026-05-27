import React, { useRef, useEffect, useCallback, useState } from 'react';
import type { PCBData, LayerVisibility, Feature, Violation } from './PCBViewer';

interface PCBCanvasProps {
  data: PCBData;
  layerVisibility: LayerVisibility;
  zoom: number;
  pan: { x: number; y: number };
  onPanChange: (pan: { x: number; y: number }) => void;
  measureMode: boolean;
  selectedViolation?: string | null;
  onViolationClick?: (violation: Violation) => void;
  highlightedNet?: string | null;
  onNetHover?: (net: string | null) => void;
}

// Highlight color for selected net
const NET_HIGHLIGHT_COLOR = '#00ff88';
const DIMMED_ALPHA = 0.2;

const LAYER_COLORS: Record<string, string> = {
  top: '#ff4444',
  bottom: '#4444ff',
  soldermask_top: '#00aa0066',
  soldermask_bottom: '#00aa0066',
  silkscreen_top: '#ffffff',
  silkscreen_bottom: '#ffff00',
  drill: '#666666',
  outline: '#ffffff',
  inner1: '#aa4444',
  inner2: '#4444aa',
};

export default function PCBCanvas({
  data,
  layerVisibility,
  zoom,
  pan,
  onPanChange,
  measureMode,
  selectedViolation,
  onViolationClick,
  highlightedNet,
  onNetHover,
}: PCBCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [measureStart, setMeasureStart] = useState<{ x: number; y: number } | null>(null);
  const [measureEnd, setMeasureEnd] = useState<{ x: number; y: number } | null>(null);

  // Convert PCB coordinates to canvas coordinates
  const pcbToCanvas = useCallback((x: number, y: number, canvas: HTMLCanvasElement) => {
    const scale = Math.min(
      canvas.width / data.board_width_mm,
      canvas.height / data.board_height_mm
    ) * zoom * 0.9;

    const offsetX = (canvas.width - data.board_width_mm * scale) / 2 + pan.x;
    const offsetY = (canvas.height - data.board_height_mm * scale) / 2 + pan.y;

    return {
      x: x * scale + offsetX,
      y: (data.board_height_mm - y) * scale + offsetY, // Flip Y axis
    };
  }, [data.board_width_mm, data.board_height_mm, zoom, pan]);

  // Convert canvas coordinates to PCB coordinates
  const canvasToPcb = useCallback((canvasX: number, canvasY: number, canvas: HTMLCanvasElement) => {
    const scale = Math.min(
      canvas.width / data.board_width_mm,
      canvas.height / data.board_height_mm
    ) * zoom * 0.9;

    const offsetX = (canvas.width - data.board_width_mm * scale) / 2 + pan.x;
    const offsetY = (canvas.height - data.board_height_mm * scale) / 2 + pan.y;

    return {
      x: (canvasX - offsetX) / scale,
      y: data.board_height_mm - (canvasY - offsetY) / scale,
    };
  }, [data.board_width_mm, data.board_height_mm, zoom, pan]);

  // Render PCB
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const scale = Math.min(
      canvas.width / data.board_width_mm,
      canvas.height / data.board_height_mm
    ) * zoom * 0.9;

    // Draw board outline
    if (layerVisibility.outline) {
      const topLeft = pcbToCanvas(0, data.board_height_mm, canvas);
      const bottomRight = pcbToCanvas(data.board_width_mm, 0, canvas);

      ctx.strokeStyle = LAYER_COLORS.outline;
      ctx.lineWidth = 2;
      ctx.strokeRect(
        topLeft.x,
        topLeft.y,
        bottomRight.x - topLeft.x,
        bottomRight.y - topLeft.y
      );
    }

    // Draw layers in order (bottom first)
    const layerOrder = ['bottom', 'soldermask_bottom', 'inner2', 'inner1', 'soldermask_top', 'top', 'silkscreen_bottom', 'silkscreen_top', 'drill'];

    // Collect all features for net highlighting
    const allFeatures: { feature: Feature; layerName: string }[] = [];

    for (const layerName of layerOrder) {
      const layerKey = layerName as keyof LayerVisibility;
      if (!layerVisibility[layerKey]) continue;

      const layer = data.layers.find(l => l.name === layerName || l.type === layerName);
      if (!layer) continue;

      for (const feature of layer.features) {
        allFeatures.push({ feature, layerName });
      }
    }

    // Two-pass rendering when net is highlighted
    if (highlightedNet) {
      // First pass: Draw dimmed non-highlighted features
      ctx.globalAlpha = DIMMED_ALPHA;
      for (const { feature, layerName } of allFeatures) {
        if (feature.net === highlightedNet) continue;  // Skip highlighted net
        ctx.strokeStyle = LAYER_COLORS[layerName] || '#888888';
        ctx.fillStyle = LAYER_COLORS[layerName] || '#888888';
        drawFeature(ctx, feature, scale, canvas);
      }
      ctx.globalAlpha = 1;

      // Second pass: Draw highlighted net with glow effect
      const highlightedFeatures = allFeatures.filter(({ feature }) => feature.net === highlightedNet);

      // Draw glow/shadow
      ctx.shadowColor = NET_HIGHLIGHT_COLOR;
      ctx.shadowBlur = 8;
      ctx.strokeStyle = NET_HIGHLIGHT_COLOR;
      ctx.fillStyle = NET_HIGHLIGHT_COLOR;

      for (const { feature } of highlightedFeatures) {
        drawFeature(ctx, feature, scale, canvas);
      }

      // Reset shadow
      ctx.shadowBlur = 0;
    } else {
      // Normal rendering without highlighting
      for (const { feature, layerName } of allFeatures) {
        ctx.strokeStyle = LAYER_COLORS[layerName] || '#888888';
        ctx.fillStyle = LAYER_COLORS[layerName] || '#888888';
        drawFeature(ctx, feature, scale, canvas);
      }
    }

    // Draw violations
    if (data.violations) {
      for (const violation of data.violations) {
        const pos = pcbToCanvas(violation.location.x, violation.location.y, canvas);
        const isSelected = violation.id === selectedViolation;

        ctx.beginPath();
        ctx.arc(pos.x, pos.y, isSelected ? 12 : 8, 0, Math.PI * 2);

        if (violation.severity === 'error') {
          ctx.fillStyle = isSelected ? '#ff0000' : '#ff000088';
        } else if (violation.severity === 'warning') {
          ctx.fillStyle = isSelected ? '#ffaa00' : '#ffaa0088';
        } else {
          ctx.fillStyle = isSelected ? '#0088ff' : '#0088ff88';
        }

        ctx.fill();

        if (isSelected) {
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }
    }

    // Draw highlighted net name indicator
    if (highlightedNet) {
      const highlightedCount = allFeatures.filter(({ feature }) => feature.net === highlightedNet).length;
      ctx.fillStyle = NET_HIGHLIGHT_COLOR;
      ctx.font = 'bold 14px monospace';
      ctx.fillText(`Net: ${highlightedNet} (${highlightedCount} features)`, 10, canvas.height - 10);
    }

    // Draw measurement line
    if (measureStart && measureEnd) {
      const start = pcbToCanvas(measureStart.x, measureStart.y, canvas);
      const end = pcbToCanvas(measureEnd.x, measureEnd.y, canvas);

      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(end.x, end.y);
      ctx.strokeStyle = '#00ff00';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Draw distance label
      const distance = Math.sqrt(
        Math.pow(measureEnd.x - measureStart.x, 2) +
        Math.pow(measureEnd.y - measureStart.y, 2)
      );
      const midX = (start.x + end.x) / 2;
      const midY = (start.y + end.y) / 2;

      ctx.fillStyle = '#00ff00';
      ctx.font = '14px monospace';
      ctx.fillText(`${distance.toFixed(2)} mm`, midX + 10, midY - 10);
    }
  }, [data, layerVisibility, zoom, pan, selectedViolation, highlightedNet, measureStart, measureEnd, pcbToCanvas]);

  const drawFeature = (
    ctx: CanvasRenderingContext2D,
    feature: Feature,
    scale: number,
    canvas: HTMLCanvasElement
  ) => {
    const points = feature.points.map(p => pcbToCanvas(p.x, p.y, canvas));

    switch (feature.type) {
      case 'trace':
        if (points.length < 2) return;
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
          ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.lineWidth = (feature.width || 0.2) * scale;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.stroke();
        break;

      case 'pad':
      case 'via':
        if (points.length < 1) return;
        const radius = ((feature.width || 0.8) / 2) * scale;
        ctx.beginPath();
        ctx.arc(points[0].x, points[0].y, radius, 0, Math.PI * 2);
        ctx.fill();

        // Draw drill hole for vias
        if (feature.type === 'via') {
          ctx.beginPath();
          ctx.arc(points[0].x, points[0].y, radius * 0.4, 0, Math.PI * 2);
          ctx.fillStyle = '#1a1a2e';
          ctx.fill();
        }
        break;

      case 'region':
        if (points.length < 3) return;
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
          ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.closePath();
        ctx.globalAlpha = 0.3;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1;
        ctx.stroke();
        break;

      case 'arc':
        // Simplified arc rendering
        if (points.length < 2) return;
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
          ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.lineWidth = (feature.width || 0.2) * scale;
        ctx.stroke();
        break;
    }
  };

  // Store latest render function in a ref to avoid dependency issues
  const renderRef = useRef(render);
  useEffect(() => {
    renderRef.current = render;
  }, [render]);

  // Handle resize - only re-create observer when container changes, not when render changes
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    // Set initial size
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;

    const resizeObserver = new ResizeObserver((entries) => {
      // Only update if dimensions actually changed
      const entry = entries[0];
      if (!entry) return;

      const newWidth = Math.floor(entry.contentRect.width);
      const newHeight = Math.floor(entry.contentRect.height);

      if (canvas.width !== newWidth || canvas.height !== newHeight) {
        canvas.width = newWidth;
        canvas.height = newHeight;
        renderRef.current();
      }
    });

    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, []); // Empty dependency - only run once on mount

  // Re-render on data/visibility changes
  useEffect(() => {
    render();
  }, [render]);

  // Mouse handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (measureMode) {
      const pcbPos = canvasToPcb(x, y, canvas);
      setMeasureStart(pcbPos);
      setMeasureEnd(null);
    } else {
      setIsDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    if (measureMode && measureStart) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      setMeasureEnd(canvasToPcb(x, y, canvas));
    } else if (isDragging) {
      onPanChange({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleClick = (e: React.MouseEvent) => {
    if (!onViolationClick || !data.violations) return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    // Check if click is near a violation
    for (const violation of data.violations) {
      const pos = pcbToCanvas(violation.location.x, violation.location.y, canvas);
      const dist = Math.sqrt(Math.pow(clickX - pos.x, 2) + Math.pow(clickY - pos.y, 2));

      if (dist < 15) {
        onViolationClick(violation);
        return;
      }
    }
  };

  // Attach non-passive wheel listener to allow preventDefault
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      // Zoom functionality would need onZoomChange callback to work
      // const delta = e.deltaY > 0 ? 0.9 : 1.1;
      // const newZoom = Math.max(0.1, Math.min(10, zoom * delta));
    };

    // Add wheel listener with passive: false to allow preventDefault
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [zoom]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full cursor-crosshair"
      style={{ minHeight: '400px' }}
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleClick}
        className="w-full h-full"
      />
    </div>
  );
}
