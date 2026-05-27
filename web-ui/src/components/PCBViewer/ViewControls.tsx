import React from 'react';

interface ViewControlsProps {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomFit: () => void;
  measureMode: boolean;
  onMeasureToggle: () => void;
}

export default function ViewControls({
  zoom,
  onZoomIn,
  onZoomOut,
  onZoomFit,
  measureMode,
  onMeasureToggle,
}: ViewControlsProps) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center bg-gray-700 rounded overflow-hidden">
        <button
          onClick={onZoomOut}
          className="px-3 py-1.5 text-gray-300 hover:bg-gray-600 transition-colors"
          title="Zoom Out"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
          </svg>
        </button>
        <span className="px-3 py-1.5 text-gray-300 text-sm min-w-[60px] text-center border-x border-gray-600">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={onZoomIn}
          className="px-3 py-1.5 text-gray-300 hover:bg-gray-600 transition-colors"
          title="Zoom In"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
        </button>
      </div>

      <button
        onClick={onZoomFit}
        className="px-3 py-1.5 bg-gray-700 text-gray-300 rounded hover:bg-gray-600 transition-colors"
        title="Fit to View"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
        </svg>
      </button>

      <button
        onClick={onMeasureToggle}
        className={`
          px-3 py-1.5 rounded transition-colors
          ${measureMode
            ? 'bg-green-600 text-white'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}
        `}
        title="Measure Tool"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M3 7h4m0 0V3m0 4l3 3M21 17h-4m0 0v4m0-4l-3-3" />
        </svg>
      </button>
    </div>
  );
}
