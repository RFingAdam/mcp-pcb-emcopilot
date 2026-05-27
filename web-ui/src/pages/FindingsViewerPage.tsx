import React, { useState, useMemo } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { agentApi, layoutsApi, simulationsApi } from '../api/client';
import { PCBViewer } from '../components/PCBViewer';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

// TypeScript interfaces matching backend Finding dataclass
interface AIFinding {
  id: string;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  title: string;
  description: string;
  location?: string;
  evidence?: Record<string, any>;
  recommendation?: string;
  confidence: number;
  related_findings: string[];
  metadata?: Record<string, any>;
}

interface FindingsResponse {
  review_id: string;
  total: number;
  offset: number;
  limit: number;
  findings: AIFinding[];
}

interface FilterState {
  severity: string[];
  category: string[];
  search: string;
}

// Styling constants
const SEVERITY_COLORS: Record<string, string> = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#ca8a04',
  low: '#0284c7',
  info: '#6b7280',
};

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

const CATEGORY_LABELS: Record<string, string> = {
  si: 'Signal Integrity',
  pi: 'Power Integrity',
  emc: 'EMC',
  dfm: 'DFM',
  thermal: 'Thermal',
  signal_integrity: 'Signal Integrity',
  power_integrity: 'Power Integrity',
  routing: 'Routing',
  impedance: 'Impedance',
  crosstalk: 'Crosstalk',
  pdn: 'PDN',
  decoupling: 'Decoupling',
};

const CATEGORY_ICONS: Record<string, string> = {
  si: '📶',
  pi: '⚡',
  emc: '📡',
  dfm: '🔧',
  thermal: '🌡️',
  signal_integrity: '📶',
  power_integrity: '⚡',
  routing: '🛤️',
  impedance: '📊',
  crosstalk: '🔀',
  pdn: '⚡',
  decoupling: '🔋',
};

// Transform API PCB data to PCBViewer's expected format
function transformPCBData(pcbData: any, violations: any[]) {
  const boardWidth = pcbData.layout?.board_width_mm ?? 100;
  const boardHeight = pcbData.layout?.board_height_mm ?? 100;

  // Group features by layer
  const layerFeatures: Record<string, any[]> = {};

  // Helper to add feature to a layer
  const addToLayer = (layerName: string, feature: any) => {
    if (!layerFeatures[layerName]) {
      layerFeatures[layerName] = [];
    }
    layerFeatures[layerName].push(feature);
  };

  // Parse geometry string (could be JSON, WKT, or coordinate list)
  const parseGeometry = (geometry: any): { x: number; y: number }[] => {
    if (!geometry) return [];

    // If it's already an array of points
    if (Array.isArray(geometry)) {
      return geometry.map((p: any) => ({
        x: p.x ?? p[0] ?? 0,
        y: p.y ?? p[1] ?? 0,
      }));
    }

    // If it's a string, try to parse it
    if (typeof geometry === 'string') {
      try {
        // Try JSON first
        const parsed = JSON.parse(geometry);
        if (Array.isArray(parsed)) {
          return parsed.map((p: any) => ({
            x: p.x ?? p[0] ?? 0,
            y: p.y ?? p[1] ?? 0,
          }));
        }
        if (parsed.coordinates) {
          return parsed.coordinates.map((c: any) => ({ x: c[0], y: c[1] }));
        }
      } catch {
        // Try WKT LINESTRING format: LINESTRING(x1 y1, x2 y2, ...)
        const match = geometry.match(/LINESTRING\s*\(([^)]+)\)/i);
        if (match) {
          const coords = match[1].split(',').map((pair: string) => {
            const [x, y] = pair.trim().split(/\s+/).map(Number);
            return { x: x || 0, y: y || 0 };
          });
          return coords;
        }
      }
    }

    // If it's an object with coordinates
    if (geometry.coordinates) {
      return geometry.coordinates.map((c: any) => ({ x: c[0], y: c[1] }));
    }

    return [];
  };

  // Transform traces
  if (pcbData.traces) {
    for (const trace of pcbData.traces) {
      const points = parseGeometry(trace.geometry);
      // If no geometry, create a simple line from start/end if available
      if (points.length === 0 && trace.start_x != null && trace.start_y != null) {
        points.push({ x: trace.start_x, y: trace.start_y });
        if (trace.end_x != null && trace.end_y != null) {
          points.push({ x: trace.end_x, y: trace.end_y });
        }
      }
      // If still no points but we have length, create a placeholder
      if (points.length === 0 && trace.length_mm) {
        // Create a horizontal trace as placeholder
        points.push({ x: 10, y: boardHeight / 2 });
        points.push({ x: 10 + trace.length_mm, y: boardHeight / 2 });
      }

      if (points.length >= 2) {
        addToLayer(trace.layer || 'top', {
          type: 'trace',
          points,
          width: trace.width_mm || 0.2,
          layer: trace.layer || 'top',
          net: trace.net_name,
        });
      }
    }
  }

  // Transform vias
  if (pcbData.vias) {
    for (const via of pcbData.vias) {
      if (via.x_mm != null && via.y_mm != null) {
        addToLayer('drill', {
          type: 'via',
          points: [{ x: via.x_mm, y: via.y_mm }],
          width: via.pad_diameter_mm || via.drill_diameter_mm || 0.5,
          layer: 'drill',
          net: via.net_name,
        });
      }
    }
  }

  // Transform components as rectangular regions
  if (pcbData.components) {
    for (const comp of pcbData.components) {
      if (comp.x_mm != null && comp.y_mm != null) {
        const halfW = (comp.width_mm || 2) / 2;
        const halfH = (comp.height_mm || 1) / 2;
        const layerName = comp.layer === 'bottom' ? 'bottom' : 'top';

        addToLayer(layerName, {
          type: 'region',
          points: [
            { x: comp.x_mm - halfW, y: comp.y_mm - halfH },
            { x: comp.x_mm + halfW, y: comp.y_mm - halfH },
            { x: comp.x_mm + halfW, y: comp.y_mm + halfH },
            { x: comp.x_mm - halfW, y: comp.y_mm + halfH },
          ],
          width: 0,
          layer: layerName,
          net: undefined,
        });
      }
    }
  }

  // Build layers array from the grouped features
  const standardLayers = ['top', 'bottom', 'inner1', 'inner2', 'soldermask_top', 'soldermask_bottom', 'silkscreen_top', 'silkscreen_bottom', 'drill', 'outline'];
  const layers = standardLayers.map(name => ({
    name,
    type: name.includes('silkscreen') ? 'silkscreen' :
          name.includes('soldermask') ? 'soldermask' :
          name === 'drill' ? 'drill' :
          name === 'outline' ? 'outline' : 'signal',
    features: layerFeatures[name] || [],
  }));

  // Add any custom layers from pcbData.layer_stack
  if (pcbData.layer_stack) {
    for (const stackLayer of pcbData.layer_stack) {
      const layerName = stackLayer.name || `Layer ${stackLayer.layer_number}`;
      if (!layers.some(l => l.name === layerName)) {
        layers.push({
          name: layerName,
          type: stackLayer.layer_type || 'signal',
          features: layerFeatures[layerName] || [],
        });
      }
    }
  }

  return {
    board_width_mm: boardWidth,
    board_height_mm: boardHeight,
    layers,
    violations,
  };
}

export default function FindingsViewerPage() {
  const { reviewId } = useParams<{ reviewId: string }>();
  const [searchParams] = useSearchParams();
  const layoutId = searchParams.get('layoutId');

  const [filters, setFilters] = useState<FilterState>({
    severity: ['critical', 'high', 'medium', 'low', 'info'],
    category: [],
    search: '',
  });
  const [selectedFinding, setSelectedFinding] = useState<AIFinding | null>(null);
  const [sortBy, setSortBy] = useState<'severity' | 'category' | 'confidence'>('severity');
  const [showViewer, setShowViewer] = useState(false);
  const [showSimulations, setShowSimulations] = useState(false);
  const [selectedSimRunId, setSelectedSimRunId] = useState<number | null>(null);

  // Fetch findings from API
  const { data: findingsData, isLoading, error } = useQuery({
    queryKey: ['findings', reviewId],
    queryFn: () => agentApi.getFindings(reviewId!, { limit: 500 }),
    enabled: !!reviewId,
  });

  // Fetch PCB data for viewer (optional)
  const { data: pcbData } = useQuery({
    queryKey: ['pcb-data', layoutId],
    queryFn: () => layoutsApi.getPCBData(Number(layoutId)),
    enabled: !!layoutId && showViewer,
  });

  // Fetch simulations for layout
  const { data: simulationsData } = useQuery({
    queryKey: ['simulations-by-layout', layoutId],
    queryFn: () => simulationsApi.getByLayout(Number(layoutId)),
    enabled: !!layoutId && showSimulations,
  });

  // Fetch results for selected simulation run
  const { data: simResults } = useQuery({
    queryKey: ['sim-results', selectedSimRunId],
    queryFn: () => simulationsApi.getResults(selectedSimRunId!),
    enabled: !!selectedSimRunId,
  });

  // Fetch metrics for selected simulation run
  const { data: simMetrics } = useQuery({
    queryKey: ['sim-metrics', selectedSimRunId],
    queryFn: () => simulationsApi.getMetrics(selectedSimRunId!),
    enabled: !!selectedSimRunId,
  });

  // Filter and sort findings
  const filteredFindings = useMemo(() => {
    if (!findingsData?.findings) return [];

    let result = findingsData.findings.filter((f: AIFinding) => {
      // Severity filter
      if (!filters.severity.includes(f.severity)) return false;
      // Category filter (if any selected)
      if (filters.category.length > 0 && !filters.category.includes(f.category)) return false;
      // Search filter
      if (filters.search) {
        const searchLower = filters.search.toLowerCase();
        return (
          f.title.toLowerCase().includes(searchLower) ||
          f.description.toLowerCase().includes(searchLower) ||
          f.location?.toLowerCase().includes(searchLower) ||
          f.recommendation?.toLowerCase().includes(searchLower)
        );
      }
      return true;
    });

    // Sort
    result.sort((a: AIFinding, b: AIFinding) => {
      if (sortBy === 'severity') {
        return SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
      } else if (sortBy === 'category') {
        return a.category.localeCompare(b.category);
      } else {
        return b.confidence - a.confidence;
      }
    });

    return result;
  }, [findingsData, filters, sortBy]);

  // Calculate counts by severity
  const counts = useMemo(() => {
    if (!findingsData?.findings) return { critical: 0, high: 0, medium: 0, low: 0, info: 0, total: 0 };

    const findings = findingsData.findings;
    return {
      critical: findings.filter((f: AIFinding) => f.severity === 'critical').length,
      high: findings.filter((f: AIFinding) => f.severity === 'high').length,
      medium: findings.filter((f: AIFinding) => f.severity === 'medium').length,
      low: findings.filter((f: AIFinding) => f.severity === 'low').length,
      info: findings.filter((f: AIFinding) => f.severity === 'info').length,
      total: findings.length,
    };
  }, [findingsData]);

  // Get unique categories for filter
  const availableCategories = useMemo(() => {
    if (!findingsData?.findings) return [];
    return Array.from(new Set(findingsData.findings.map((f: AIFinding) => f.category)));
  }, [findingsData]);

  const handleSeverityToggle = (severity: string) => {
    setFilters((prev) => ({
      ...prev,
      severity: prev.severity.includes(severity)
        ? prev.severity.filter((s) => s !== severity)
        : [...prev.severity, severity],
    }));
  };

  const handleCategoryToggle = (category: string) => {
    setFilters((prev) => ({
      ...prev,
      category: prev.category.includes(category)
        ? prev.category.filter((c) => c !== category)
        : [...prev.category, category],
    }));
  };

  // Parse S-parameter data for charts
  const sParamChartData = useMemo(() => {
    if (!simResults) return [];
    const sParamResult = simResults.find((r: any) => r.result_type === 's_parameters');
    if (!sParamResult?.data) return [];

    const data = sParamResult.data;
    const frequencies = data.frequencies_hz || data.frequencies_ghz?.map((f: number) => f * 1e9) || [];
    const s11 = data.s11_db || [];
    const s21 = data.s21_db || [];

    return frequencies.map((freq: number, idx: number) => ({
      frequency_ghz: freq / 1e9,
      s11_db: s11[idx] ?? null,
      s21_db: s21[idx] ?? null,
    }));
  }, [simResults]);

  // Extract affected components from finding location/evidence
  const parseAffectedComponents = (finding: AIFinding) => {
    const components: string[] = [];
    const nets: string[] = [];

    // Parse from location string
    if (finding.location) {
      // Match component references like U1, C10, R5, etc.
      const compMatches = finding.location.match(/\b([A-Z]+\d+)\b/g);
      if (compMatches) components.push(...compMatches);

      // Match net names
      const netMatches = finding.location.match(/net[:\s]+([^\s,()]+)/gi);
      if (netMatches) {
        nets.push(...netMatches.map(m => m.replace(/net[:\s]+/i, '')));
      }
    }

    // Parse from evidence
    if (finding.evidence) {
      if (finding.evidence.components) {
        components.push(...(Array.isArray(finding.evidence.components)
          ? finding.evidence.components
          : [finding.evidence.components]));
      }
      if (finding.evidence.nets) {
        nets.push(...(Array.isArray(finding.evidence.nets)
          ? finding.evidence.nets
          : [finding.evidence.nets]));
      }
      if (finding.evidence.affected_nets) {
        nets.push(...(Array.isArray(finding.evidence.affected_nets)
          ? finding.evidence.affected_nets
          : [finding.evidence.affected_nets]));
      }
      if (finding.evidence.component) {
        components.push(finding.evidence.component);
      }
      if (finding.evidence.net) {
        nets.push(finding.evidence.net);
      }
    }

    return {
      components: [...new Set(components)],
      nets: [...new Set(nets)],
    };
  };

  // Convert findings to violations format for PCBViewer
  const viewerViolations = useMemo(() => {
    if (!findingsData?.findings) return [];

    return findingsData.findings
      .filter((f: AIFinding) => f.location)
      .map((f: AIFinding) => {
        // Try to parse coordinates from location string
        const coordMatch = f.location?.match(/\((-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)/);
        const netMatch = f.location?.match(/net[:\s]+([^\s,]+)/i);

        return {
          id: f.id,
          type: f.category,
          severity: ['critical', 'high'].includes(f.severity) ? 'error' as const :
                   f.severity === 'medium' ? 'warning' as const : 'info' as const,
          message: f.title,
          location: {
            x: coordMatch ? parseFloat(coordMatch[1]) : 0,
            y: coordMatch ? parseFloat(coordMatch[2]) : 0,
          },
          net_name: netMatch ? netMatch[1] : undefined,
        };
      });
  }, [findingsData]);

  if (isLoading) {
    return (
      <div className="container mt-4">
        <div className="card">
          <div className="card-body text-center">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
            <p className="mt-2">Loading findings...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mt-4">
        <div className="alert alert-danger">
          Failed to load findings: {String(error)}
        </div>
        <Link to="/" className="btn btn-secondary">Back to Projects</Link>
      </div>
    );
  }

  return (
    <div className="container-fluid mt-3" style={{ maxWidth: '1600px' }}>
      {/* Header */}
      <div className="d-flex justify-content-between align-items-center mb-3">
        <div>
          <Link to="/" className="btn btn-outline-secondary btn-sm me-2">
            ← Back
          </Link>
          <h4 className="d-inline mb-0">AI Review Findings</h4>
          <small className="text-muted ms-2">Review: {reviewId?.substring(0, 8)}...</small>
        </div>
        <div className="d-flex gap-2">
          {layoutId && (
            <>
              <button
                className={`btn ${showViewer ? 'btn-primary' : 'btn-outline-primary'} btn-sm`}
                onClick={() => setShowViewer(!showViewer)}
              >
                {showViewer ? '🗺️ Hide PCB Viewer' : '🗺️ Show PCB Viewer'}
              </button>
              <button
                className={`btn ${showSimulations ? 'btn-success' : 'btn-outline-success'} btn-sm`}
                onClick={() => setShowSimulations(!showSimulations)}
              >
                {showSimulations ? '📊 Hide Simulations' : '📊 Show Simulations'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* PCB Viewer (optional) */}
      {showViewer && pcbData && (
        <div className="card mb-3" style={{ height: '350px' }}>
          <PCBViewer
            data={transformPCBData(pcbData, viewerViolations)}
            selectedViolation={selectedFinding?.id}
            onViolationClick={(v: { id: string }) => {
              const finding = findingsData?.findings.find((f: AIFinding) => f.id === v.id);
              if (finding) setSelectedFinding(finding);
            }}
          />
        </div>
      )}

      {/* Simulation Results Section */}
      {showSimulations && (
        <div className="card mb-3">
          <div className="card-header py-2 d-flex justify-content-between align-items-center">
            <h6 className="mb-0">📊 EM Simulation Results</h6>
            {simulationsData?.simulations?.length > 0 && (
              <span className="badge bg-info">{simulationsData.simulations.length} simulations</span>
            )}
          </div>
          <div className="card-body">
            {!simulationsData?.simulations?.length ? (
              <div className="text-muted text-center py-3">
                <p className="mb-2">No simulations found for this layout.</p>
                {layoutId && pcbData?.layout?.project_id && (
                  <Link
                    to={`/projects/${pcbData.layout.project_id}/simulations/new?layoutId=${layoutId}`}
                    className="btn btn-primary btn-sm"
                  >
                    🚀 Run New Simulation
                  </Link>
                )}
              </div>
            ) : (
              <div className="row">
                {/* Simulation Selector */}
                <div className="col-md-3">
                  <label className="form-label small fw-bold">Select Simulation Run</label>
                  <div className="list-group list-group-flush" style={{ maxHeight: '250px', overflowY: 'auto' }}>
                    {simulationsData.simulations.flatMap((sim: any) =>
                      sim.runs.map((run: any) => (
                        <button
                          key={run.id}
                          className={`list-group-item list-group-item-action py-2 ${selectedSimRunId === run.id ? 'active' : ''}`}
                          onClick={() => setSelectedSimRunId(run.id)}
                        >
                          <div className="d-flex justify-content-between align-items-center">
                            <span className="small fw-bold">{sim.name || `Sim #${sim.id}`}</span>
                            <span className={`badge ${run.status === 'completed' ? 'bg-success' : run.status === 'running' ? 'bg-warning' : 'bg-secondary'}`}>
                              {run.status}
                            </span>
                          </div>
                          <small className="text-muted d-block">
                            Run #{run.id} • {sim.simulation_type}
                          </small>
                          {run.metrics_summary && run.metrics_summary.s11_max_db != null && (
                            <small className="text-muted d-block">
                              S11: {run.metrics_summary.s11_max_db.toFixed(1)}dB
                            </small>
                          )}
                        </button>
                      ))
                    )}
                  </div>
                  {layoutId && pcbData?.layout?.project_id && (
                    <Link
                      to={`/projects/${pcbData.layout.project_id}/simulations/new?layoutId=${layoutId}`}
                      className="btn btn-outline-primary btn-sm w-100 mt-2"
                    >
                      + New Simulation
                    </Link>
                  )}
                </div>

                {/* Results Display */}
                <div className="col-md-9">
                  {!selectedSimRunId ? (
                    <div className="text-muted text-center py-4">
                      <p>← Select a simulation run to view results</p>
                    </div>
                  ) : (
                    <div>
                      {/* S-Parameter Chart */}
                      {sParamChartData.length > 0 && (
                        <div className="mb-3">
                          <h6 className="small fw-bold mb-2">S-Parameters vs Frequency</h6>
                          <ResponsiveContainer width="100%" height={200}>
                            <LineChart data={sParamChartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                              <XAxis
                                dataKey="frequency_ghz"
                                tickFormatter={(v) => typeof v === 'number' ? v.toFixed(1) : ''}
                                label={{ value: 'Frequency (GHz)', position: 'bottom', offset: -5, fontSize: 11 }}
                                tick={{ fontSize: 10 }}
                              />
                              <YAxis
                                label={{ value: 'dB', angle: -90, position: 'insideLeft', fontSize: 11 }}
                                tick={{ fontSize: 10 }}
                              />
                              <Tooltip
                                formatter={(value: number) => [typeof value === 'number' ? `${value.toFixed(2)} dB` : 'N/A', '']}
                                labelFormatter={(label) => {
                                  const num = Number(label);
                                  return !isNaN(num) ? `${num.toFixed(2)} GHz` : String(label);
                                }}
                              />
                              <Legend wrapperStyle={{ fontSize: 11 }} />
                              <Line type="monotone" dataKey="s11_db" stroke="#dc2626" name="S11 (Return Loss)" dot={false} strokeWidth={2} />
                              <Line type="monotone" dataKey="s21_db" stroke="#2563eb" name="S21 (Insertion Loss)" dot={false} strokeWidth={2} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      )}

                      {/* Metrics Summary */}
                      {simMetrics && (
                        <div className="row g-2">
                          {simMetrics.return_loss_db !== undefined && (
                            <div className="col-md-3">
                              <div className={`card h-100 ${simMetrics.return_loss_db < -10 ? 'border-success' : 'border-warning'}`}>
                                <div className="card-body py-2 text-center">
                                  <div className="small text-muted">Return Loss</div>
                                  <div className="fw-bold">{simMetrics.return_loss_db.toFixed(1)} dB</div>
                                </div>
                              </div>
                            </div>
                          )}
                          {simMetrics.insertion_loss_db !== undefined && (
                            <div className="col-md-3">
                              <div className={`card h-100 ${simMetrics.insertion_loss_db > -3 ? 'border-success' : 'border-warning'}`}>
                                <div className="card-body py-2 text-center">
                                  <div className="small text-muted">Insertion Loss</div>
                                  <div className="fw-bold">{simMetrics.insertion_loss_db.toFixed(1)} dB</div>
                                </div>
                              </div>
                            </div>
                          )}
                          {simMetrics.impedance_ohm !== undefined && (
                            <div className="col-md-3">
                              <div className="card h-100">
                                <div className="card-body py-2 text-center">
                                  <div className="small text-muted">Impedance</div>
                                  <div className="fw-bold">{simMetrics.impedance_ohm.toFixed(1)} Ω</div>
                                </div>
                              </div>
                            </div>
                          )}
                          {simMetrics.bandwidth_ghz !== undefined && (
                            <div className="col-md-3">
                              <div className="card h-100">
                                <div className="card-body py-2 text-center">
                                  <div className="small text-muted">Bandwidth</div>
                                  <div className="fw-bold">{simMetrics.bandwidth_ghz.toFixed(2)} GHz</div>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Link to full results */}
                      {selectedSimRunId && (
                        <div className="text-end mt-2">
                          <Link to={`/simulations/runs/${selectedSimRunId}`} className="btn btn-outline-primary btn-sm">
                            View Full Results →
                          </Link>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="row g-2 mb-3">
        {[
          { key: 'critical', label: 'Critical', color: SEVERITY_COLORS.critical },
          { key: 'high', label: 'High', color: SEVERITY_COLORS.high },
          { key: 'medium', label: 'Medium', color: SEVERITY_COLORS.medium },
          { key: 'low', label: 'Low', color: SEVERITY_COLORS.low },
          { key: 'info', label: 'Info', color: SEVERITY_COLORS.info },
        ].map(({ key, label, color }) => (
          <div className="col" key={key}>
            <div
              className={`card h-100 ${filters.severity.includes(key) ? '' : 'opacity-50'}`}
              style={{ borderLeft: `4px solid ${color}`, cursor: 'pointer' }}
              onClick={() => handleSeverityToggle(key)}
            >
              <div className="card-body text-center py-2">
                <div style={{ fontSize: '1.75rem', fontWeight: 'bold', color }}>
                  {counts[key as keyof typeof counts]}
                </div>
                <div className="small text-muted">{label}</div>
              </div>
            </div>
          </div>
        ))}
        <div className="col">
          <div className="card h-100" style={{ borderLeft: '4px solid #6c757d' }}>
            <div className="card-body text-center py-2">
              <div style={{ fontSize: '1.75rem', fontWeight: 'bold' }}>
                {filteredFindings.length}
              </div>
              <div className="small text-muted">Showing</div>
            </div>
          </div>
        </div>
      </div>

      {/* Filters Row */}
      <div className="card mb-3">
        <div className="card-body py-2">
          <div className="row g-2 align-items-center">
            {/* Category Filters */}
            <div className="col-auto">
              <label className="form-label mb-0 me-2 small fw-bold">Category:</label>
              <div className="btn-group btn-group-sm">
                {availableCategories.map((cat: string) => (
                  <button
                    key={cat}
                    className={`btn ${filters.category.includes(cat) ? 'btn-primary' : 'btn-outline-secondary'}`}
                    onClick={() => handleCategoryToggle(cat)}
                  >
                    {CATEGORY_ICONS[cat] || '📋'} {CATEGORY_LABELS[cat] || cat}
                  </button>
                ))}
                {filters.category.length > 0 && (
                  <button
                    className="btn btn-outline-danger"
                    onClick={() => setFilters(prev => ({ ...prev, category: [] }))}
                    title="Clear category filter"
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>

            {/* Search */}
            <div className="col">
              <input
                type="text"
                className="form-control form-control-sm"
                placeholder="Search findings..."
                value={filters.search}
                onChange={(e) => setFilters((prev) => ({ ...prev, search: e.target.value }))}
              />
            </div>

            {/* Sort */}
            <div className="col-auto">
              <select
                className="form-select form-select-sm"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
              >
                <option value="severity">Sort by Severity</option>
                <option value="category">Sort by Category</option>
                <option value="confidence">Sort by Confidence</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* Findings List and Detail Panel */}
      <div className="row">
        {/* Findings List */}
        <div className={selectedFinding ? 'col-md-7' : 'col-12'}>
          <div style={{ maxHeight: 'calc(100vh - 350px)', overflowY: 'auto' }}>
            {filteredFindings.length === 0 ? (
              <div className="card">
                <div className="card-body text-center text-muted">
                  <p className="mb-0">No findings match the current filters</p>
                </div>
              </div>
            ) : (
              filteredFindings.map((finding: AIFinding) => (
                <div
                  key={finding.id}
                  className={`card mb-2 ${selectedFinding?.id === finding.id ? 'border-primary' : ''}`}
                  style={{
                    cursor: 'pointer',
                    borderLeft: `4px solid ${SEVERITY_COLORS[finding.severity]}`,
                    transition: 'box-shadow 0.15s',
                  }}
                  onClick={() => setSelectedFinding(finding)}
                >
                  <div className="card-body py-2 px-3">
                    <div className="d-flex justify-content-between align-items-start">
                      <div className="d-flex align-items-start">
                        <span
                          style={{
                            width: '10px',
                            height: '10px',
                            borderRadius: '50%',
                            backgroundColor: SEVERITY_COLORS[finding.severity],
                            flexShrink: 0,
                            marginTop: '6px',
                            marginRight: '10px',
                          }}
                          title={finding.severity.toUpperCase()}
                        />
                        <div>
                          <div className="mb-1">
                            <span className="badge bg-info me-1" style={{ fontSize: '0.7rem' }}>
                              {CATEGORY_ICONS[finding.category] || '📋'} {CATEGORY_LABELS[finding.category] || finding.category}
                            </span>
                            <strong>{finding.title}</strong>
                          </div>
                          <p className="text-muted mb-1 small" style={{ maxWidth: '600px' }}>
                            {finding.description.length > 150
                              ? finding.description.substring(0, 150) + '...'
                              : finding.description}
                          </p>
                          {finding.location && (
                            <div className="small text-muted" style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                              📍 {finding.location}
                            </div>
                          )}
                        </div>
                      </div>
                      <span
                        className="badge"
                        style={{
                          backgroundColor: SEVERITY_COLORS[finding.severity] + '22',
                          color: SEVERITY_COLORS[finding.severity],
                          fontSize: '0.7rem',
                        }}
                      >
                        {finding.severity.toUpperCase()}
                      </span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Detail Panel */}
        {selectedFinding && (
          <div className="col-md-5">
            <div className="card" style={{ position: 'sticky', top: '1rem' }}>
              <div className="card-header d-flex justify-content-between align-items-center py-2">
                <h6 className="mb-0">Finding Details</h6>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => setSelectedFinding(null)}>
                  ✕
                </button>
              </div>
              <div className="card-body" style={{ maxHeight: 'calc(100vh - 400px)', overflowY: 'auto' }}>
                {/* Severity and Category badges */}
                <div className="mb-3">
                  <span
                    className="badge me-1"
                    style={{ backgroundColor: SEVERITY_COLORS[selectedFinding.severity], color: 'white' }}
                  >
                    {selectedFinding.severity.toUpperCase()}
                  </span>
                  <span className="badge bg-info">
                    {CATEGORY_LABELS[selectedFinding.category] || selectedFinding.category}
                  </span>
                </div>

                {/* Title and Description */}
                <h5>{selectedFinding.title}</h5>
                <p className="text-muted">{selectedFinding.description}</p>

                {/* Location */}
                {selectedFinding.location && (
                  <div className="mb-3">
                    <h6 className="text-muted small mb-1">Location</h6>
                    <code className="d-block p-2 bg-light rounded" style={{ fontSize: '0.8rem' }}>
                      {selectedFinding.location}
                    </code>
                  </div>
                )}

                {/* Affected Components & Nets */}
                {(() => {
                  const affected = parseAffectedComponents(selectedFinding);
                  if (affected.components.length === 0 && affected.nets.length === 0) return null;
                  return (
                    <div className="mb-3">
                      <h6 className="text-muted small mb-1">Affected Elements</h6>
                      <div className="d-flex flex-wrap gap-1">
                        {affected.components.map((comp) => (
                          <span
                            key={comp}
                            className="badge bg-warning text-dark"
                            style={{ cursor: 'pointer' }}
                            title={`Component: ${comp}`}
                          >
                            🔧 {comp}
                          </span>
                        ))}
                        {affected.nets.map((net) => (
                          <span
                            key={net}
                            className="badge bg-primary"
                            style={{ cursor: 'pointer' }}
                            title={`Net: ${net}`}
                          >
                            📶 {net}
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })()}

                {/* Recommendation */}
                {selectedFinding.recommendation && (
                  <div className="mb-3">
                    <h6 className="text-muted small mb-1">Recommendation</h6>
                    <div className="alert alert-info py-2 mb-0" style={{ fontSize: '0.9rem' }}>
                      💡 {selectedFinding.recommendation}
                    </div>
                  </div>
                )}

                {/* Evidence */}
                {selectedFinding.evidence && Object.keys(selectedFinding.evidence).length > 0 && (
                  <div className="mb-3">
                    <h6 className="text-muted small mb-1">Evidence</h6>
                    <pre className="bg-light p-2 rounded" style={{ fontSize: '0.75rem', maxHeight: '150px', overflow: 'auto' }}>
                      {JSON.stringify(selectedFinding.evidence, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Confidence */}
                <div className="mb-3">
                  <h6 className="text-muted small mb-1">Confidence</h6>
                  <div className="d-flex align-items-center">
                    <div className="progress flex-grow-1" style={{ height: '8px' }}>
                      <div
                        className={`progress-bar ${
                          selectedFinding.confidence > 0.8 ? 'bg-success' :
                          selectedFinding.confidence > 0.5 ? 'bg-warning' : 'bg-danger'
                        }`}
                        style={{ width: `${selectedFinding.confidence * 100}%` }}
                      />
                    </div>
                    <span className="ms-2 small">{(selectedFinding.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>

                {/* Related Findings */}
                {selectedFinding.related_findings && selectedFinding.related_findings.length > 0 && (
                  <div className="mb-3">
                    <h6 className="text-muted small mb-1">Related Findings</h6>
                    <div>
                      {selectedFinding.related_findings.map((relatedId: string) => (
                        <span
                          key={relatedId}
                          className="badge bg-secondary me-1"
                          style={{ cursor: 'pointer' }}
                          onClick={() => {
                            const related = findingsData?.findings.find((f: AIFinding) => f.id === relatedId);
                            if (related) setSelectedFinding(related);
                          }}
                        >
                          {relatedId.substring(0, 8)}...
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Finding ID */}
                <div className="text-muted small">
                  <span className="badge bg-light text-dark">ID: {selectedFinding.id}</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
