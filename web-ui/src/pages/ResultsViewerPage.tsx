import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { simulationsApi, aiApi } from '../api/client';
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

// Interface styling
const INTERFACE_COLORS: Record<string, { primary: string; secondary: string; icon: string }> = {
  ddr4: { primary: '#1565c0', secondary: '#e3f2fd', icon: '🧠' },
  ddr5: { primary: '#0d47a1', secondary: '#e3f2fd', icon: '🧠' },
  lpddr4: { primary: '#2e7d32', secondary: '#e8f5e9', icon: '🧠' },
  usb2: { primary: '#e65100', secondary: '#fff3e0', icon: '🔌' },
  usb3: { primary: '#bf360c', secondary: '#fff3e0', icon: '⚡' },
  pcie_gen3: { primary: '#c2185b', secondary: '#fce4ec', icon: '🚀' },
  pcie_gen4: { primary: '#880e4f', secondary: '#fce4ec', icon: '🚀' },
  pcie_gen5: { primary: '#4a148c', secondary: '#fce4ec', icon: '🚀' },
  ethernet_1g: { primary: '#00695c', secondary: '#e0f7fa', icon: '🌐' },
  ethernet_10g: { primary: '#004d40', secondary: '#e0f7fa', icon: '🌐' },
  hdmi: { primary: '#7b1fa2', secondary: '#f3e5f5', icon: '📺' },
  displayport: { primary: '#6a1b9a', secondary: '#f3e5f5', icon: '🖥️' },
  sata: { primary: '#4e342e', secondary: '#efebe9', icon: '💾' },
};

function formatFrequency(hz: number): string {
  if (hz >= 1e9) return `${(hz / 1e9).toFixed(2)} GHz`;
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(2)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(2)} kHz`;
  return `${hz} Hz`;
}

interface InterfaceResult {
  interface_type: string;
  description?: string;
  confidence: number;
  nets: string[];
  frequencies_hz: number[];
  frequencies_ghz?: number[];
  s11_db: number[];
  s21_db: number[];
  traces_analyzed: number;
  avg_impedance_ohm: number;
  target_impedance_ohm: number;
  return_loss_min_db?: number;
  insertion_loss_max_db?: number;
  error?: string;
}

export default function ResultsViewerPage() {
  const { runId } = useParams<{ runId: string }>();
  const [interpretation, setInterpretation] = useState<any>(null);
  const [isInterpreting, setIsInterpreting] = useState(false);
  const [selectedInterfaceTab, setSelectedInterfaceTab] = useState<string>('all');

  const { data: run, isLoading: runLoading } = useQuery({
    queryKey: ['run', runId],
    queryFn: () => simulationsApi.getRun(Number(runId)),
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ||
      query.state.data?.status === 'queued'
        ? 2000
        : false,
  });

  const { data: results } = useQuery({
    queryKey: ['results', runId],
    queryFn: () => simulationsApi.getResults(Number(runId)),
    enabled: run?.status === 'completed',
  });

  const { data: metrics } = useQuery({
    queryKey: ['metrics', runId],
    queryFn: () => simulationsApi.getMetrics(Number(runId)),
    enabled: run?.status === 'completed',
  });

  const handleInterpret = async () => {
    setIsInterpreting(true);
    try {
      const result = await aiApi.interpretResults({ run_id: Number(runId) });
      setInterpretation(result);
    } catch (error) {
      console.error('Interpretation failed:', error);
    } finally {
      setIsInterpreting(false);
    }
  };

  if (runLoading) return <div className="loading">Loading simulation run...</div>;
  if (!run) return <div className="error">Run not found</div>;

  const sParamResult = results?.find((r: any) => r.result_type === 's_parameters');
  const sParamData = sParamResult?.data;

  // Check if we have per-interface results
  const interfaceResults: Record<string, InterfaceResult> =
    sParamData?.interface_results || {};
  const hasMultipleInterfaces = Object.keys(interfaceResults).length > 0;

  // Prepare chart data - either from interfaces or legacy format
  const getChartData = (interfaceType?: string) => {
    if (interfaceType && interfaceResults[interfaceType]) {
      const iface = interfaceResults[interfaceType];
      if (iface.error) return [];
      return iface.frequencies_hz.map((freq: number, idx: number) => ({
        frequency_mhz: freq / 1e6,
        frequency_ghz: freq / 1e9,
        s11_db: iface.s11_db[idx],
        s21_db: iface.s21_db[idx],
      }));
    }

    // Legacy format (single result)
    if (sParamData && sParamData.frequencies_hz) {
      return sParamData.frequencies_hz.map((freq: number, idx: number) => ({
        frequency_mhz: freq / 1e6,
        frequency_ghz: freq / 1e9,
        s11_db: sParamData.s11_db[idx],
        s21_db: sParamData.s21_db[idx],
      }));
    }

    return [];
  };

  // Combined chart data for "All" view
  const getAllInterfacesChartData = () => {
    if (!hasMultipleInterfaces) return getChartData();

    // For "all" view, just show the first interface's chart
    // as combining them on one chart can be confusing
    const firstInterface = Object.keys(interfaceResults)[0];
    return getChartData(firstInterface);
  };

  const chartData =
    selectedInterfaceTab === 'all'
      ? getAllInterfacesChartData()
      : getChartData(selectedInterfaceTab);

  // Get interface-specific specs
  const getInterfaceSpecs = (interfaceType: string) => {
    const iface = interfaceResults[interfaceType];
    if (!iface) return null;

    const impedanceDeviation = Math.abs(
      ((iface.avg_impedance_ohm - iface.target_impedance_ohm) /
        iface.target_impedance_ohm) *
        100
    );

    const returnLossOk =
      iface.return_loss_min_db !== undefined && iface.return_loss_min_db < -10;
    const insertionLossOk =
      iface.insertion_loss_max_db !== undefined &&
      iface.insertion_loss_max_db > -3;
    const impedanceOk = impedanceDeviation < 10;

    return {
      ...iface,
      impedanceDeviation,
      returnLossOk,
      insertionLossOk,
      impedanceOk,
      overallPass: returnLossOk && insertionLossOk && impedanceOk,
    };
  };

  return (
    <div>
      <div className="mb-3">
        <Link to="/" className="btn btn-secondary">
          ← Back to Projects
        </Link>
      </div>

      <div className="card mb-3">
        <h1>Simulation Results</h1>
        <div className="flex gap-2 mt-2">
          <span
            className={`badge badge-${
              run.status === 'completed'
                ? 'success'
                : run.status === 'running'
                  ? 'warning'
                  : run.status === 'failed'
                    ? 'error'
                    : 'info'
            }`}
          >
            {run.status.toUpperCase()}
          </span>
          {run.progress_percent !== null && run.status === 'running' && (
            <span className="text-muted">{run.progress_percent}% complete</span>
          )}
          {sParamData?.analysis_type && (
            <span className="badge badge-info">
              {sParamData.analysis_type === 'analytical'
                ? '⚡ Analytical'
                : '🔬 OpenEMS'}
            </span>
          )}
        </div>
      </div>

      {run.status === 'completed' && (
        <>
          {/* Interface Tabs */}
          {hasMultipleInterfaces && (
            <div className="card mb-3">
              <h2>Detected Interfaces</h2>
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: '8px',
                  marginTop: '12px',
                }}
              >
                <button
                  onClick={() => setSelectedInterfaceTab('all')}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '8px',
                    border:
                      selectedInterfaceTab === 'all'
                        ? '2px solid #333'
                        : '2px solid #ddd',
                    backgroundColor:
                      selectedInterfaceTab === 'all' ? '#f5f5f5' : '#fff',
                    cursor: 'pointer',
                    fontWeight: selectedInterfaceTab === 'all' ? 600 : 400,
                  }}
                >
                  📊 Overview
                </button>
                {Object.entries(interfaceResults).map(([ifaceType, iface]) => {
                  const colors = INTERFACE_COLORS[ifaceType] || {
                    primary: '#333',
                    secondary: '#f5f5f5',
                    icon: '📡',
                  };
                  const specs = getInterfaceSpecs(ifaceType);
                  return (
                    <button
                      key={ifaceType}
                      onClick={() => setSelectedInterfaceTab(ifaceType)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 16px',
                        borderRadius: '8px',
                        border:
                          selectedInterfaceTab === ifaceType
                            ? `2px solid ${colors.primary}`
                            : '2px solid #ddd',
                        backgroundColor:
                          selectedInterfaceTab === ifaceType
                            ? colors.secondary
                            : '#fff',
                        color: colors.primary,
                        cursor: 'pointer',
                        fontWeight:
                          selectedInterfaceTab === ifaceType ? 600 : 400,
                      }}
                    >
                      <span>{colors.icon}</span>
                      <span>{ifaceType.toUpperCase()}</span>
                      {specs && !iface.error && (
                        <span
                          style={{
                            fontSize: '0.75rem',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            backgroundColor: specs.overallPass
                              ? '#c8e6c9'
                              : '#ffcdd2',
                            color: specs.overallPass ? '#2e7d32' : '#c62828',
                          }}
                        >
                          {specs.overallPass ? 'PASS' : 'CHECK'}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Interface-specific Summary */}
          {selectedInterfaceTab !== 'all' &&
            interfaceResults[selectedInterfaceTab] && (
              <div className="card mb-3">
                {(() => {
                  const specs = getInterfaceSpecs(selectedInterfaceTab);
                  if (!specs) return null;
                  if (specs.error)
                    return (
                      <p style={{ color: '#d32f2f' }}>Error: {specs.error}</p>
                    );

                  const colors = INTERFACE_COLORS[selectedInterfaceTab] || {
                    primary: '#333',
                  };

                  return (
                    <>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                        }}
                      >
                        <div>
                          <h2>
                            {specs.description ||
                              selectedInterfaceTab.toUpperCase()}{' '}
                            Analysis
                          </h2>
                          <p className="text-muted">
                            {specs.traces_analyzed} traces analyzed |{' '}
                            {specs.nets.length} nets | Confidence:{' '}
                            {Math.round(specs.confidence * 100)}%
                          </p>
                        </div>
                        <div
                          style={{
                            padding: '12px 24px',
                            borderRadius: '8px',
                            backgroundColor: specs.overallPass
                              ? '#e8f5e9'
                              : '#fff3e0',
                            border: `2px solid ${specs.overallPass ? '#4caf50' : '#ff9800'}`,
                            textAlign: 'center',
                          }}
                        >
                          <div
                            style={{
                              fontSize: '1.5rem',
                              fontWeight: 600,
                              color: specs.overallPass ? '#2e7d32' : '#e65100',
                            }}
                          >
                            {specs.overallPass ? '✓ PASS' : '⚠ REVIEW'}
                          </div>
                        </div>
                      </div>

                      <div
                        className="grid grid-3"
                        style={{ marginTop: '16px', gap: '12px' }}
                      >
                        {/* Impedance */}
                        <div
                          style={{
                            padding: '16px',
                            borderRadius: '8px',
                            backgroundColor: specs.impedanceOk
                              ? '#e8f5e9'
                              : '#ffebee',
                            border: `1px solid ${specs.impedanceOk ? '#a5d6a7' : '#ef9a9a'}`,
                          }}
                        >
                          <div
                            style={{
                              fontSize: '0.85rem',
                              color: '#666',
                              marginBottom: '4px',
                            }}
                          >
                            Avg Impedance
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>
                            {specs.avg_impedance_ohm.toFixed(1)}Ω
                          </div>
                          <div style={{ fontSize: '0.8rem', color: '#888' }}>
                            Target: {specs.target_impedance_ohm}Ω (
                            {specs.impedanceDeviation.toFixed(1)}% deviation)
                          </div>
                        </div>

                        {/* Return Loss */}
                        <div
                          style={{
                            padding: '16px',
                            borderRadius: '8px',
                            backgroundColor: specs.returnLossOk
                              ? '#e8f5e9'
                              : '#ffebee',
                            border: `1px solid ${specs.returnLossOk ? '#a5d6a7' : '#ef9a9a'}`,
                          }}
                        >
                          <div
                            style={{
                              fontSize: '0.85rem',
                              color: '#666',
                              marginBottom: '4px',
                            }}
                          >
                            Return Loss (S11 min)
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>
                            {specs.return_loss_min_db?.toFixed(2)} dB
                          </div>
                          <div style={{ fontSize: '0.8rem', color: '#888' }}>
                            Target: &lt; -10 dB
                          </div>
                        </div>

                        {/* Insertion Loss */}
                        <div
                          style={{
                            padding: '16px',
                            borderRadius: '8px',
                            backgroundColor: specs.insertionLossOk
                              ? '#e8f5e9'
                              : '#ffebee',
                            border: `1px solid ${specs.insertionLossOk ? '#a5d6a7' : '#ef9a9a'}`,
                          }}
                        >
                          <div
                            style={{
                              fontSize: '0.85rem',
                              color: '#666',
                              marginBottom: '4px',
                            }}
                          >
                            Insertion Loss (S21 max)
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>
                            {specs.insertion_loss_max_db?.toFixed(2)} dB
                          </div>
                          <div style={{ fontSize: '0.8rem', color: '#888' }}>
                            Target: &gt; -3 dB
                          </div>
                        </div>
                      </div>

                      {/* Nets analyzed */}
                      {specs.nets.length > 0 && (
                        <div style={{ marginTop: '16px' }}>
                          <h3>Analyzed Nets</h3>
                          <div
                            style={{
                              display: 'flex',
                              flexWrap: 'wrap',
                              gap: '6px',
                              marginTop: '8px',
                            }}
                          >
                            {specs.nets.slice(0, 20).map((net: string) => (
                              <span
                                key={net}
                                style={{
                                  padding: '4px 10px',
                                  borderRadius: '4px',
                                  backgroundColor: colors.secondary || '#f0f0f0',
                                  color: colors.primary || '#333',
                                  fontSize: '0.8rem',
                                  fontFamily: 'monospace',
                                }}
                              >
                                {net}
                              </span>
                            ))}
                            {specs.nets.length > 20 && (
                              <span style={{ color: '#888', fontSize: '0.8rem' }}>
                                +{specs.nets.length - 20} more
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            )}

          {/* AI Interpretation */}
          <div className="card mb-3">
            <div className="flex-between mb-2">
              <h2>AI Interpretation</h2>
              <button
                className="btn btn-primary"
                onClick={handleInterpret}
                disabled={isInterpreting}
              >
                {isInterpreting
                  ? 'Analyzing...'
                  : interpretation
                    ? 'Refresh Analysis'
                    : 'Get AI Insights'}
              </button>
            </div>

            {interpretation && (
              <div>
                <p className="mb-3">{interpretation.summary}</p>

                {interpretation.key_findings &&
                  interpretation.key_findings.length > 0 && (
                    <div className="mb-3">
                      <h3>Key Findings</h3>
                      <ul>
                        {interpretation.key_findings.map(
                          (finding: string, idx: number) => (
                            <li key={idx}>{finding}</li>
                          )
                        )}
                      </ul>
                    </div>
                  )}

                {interpretation.issues && interpretation.issues.length > 0 && (
                  <div className="mb-3">
                    <h3>Issues Identified</h3>
                    <ul>
                      {interpretation.issues.map((issue: string, idx: number) => (
                        <li key={idx} className="text-warning">
                          {issue}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {interpretation.recommendations &&
                  interpretation.recommendations.length > 0 && (
                    <div>
                      <h3>Recommendations</h3>
                      <ul>
                        {interpretation.recommendations.map(
                          (rec: string, idx: number) => (
                            <li key={idx}>{rec}</li>
                          )
                        )}
                      </ul>
                    </div>
                  )}
              </div>
            )}
          </div>

          {/* S-Parameter Chart */}
          {chartData.length > 0 && (
            <div className="card mb-3">
              <h2>
                S-Parameters
                {selectedInterfaceTab !== 'all' &&
                  ` - ${selectedInterfaceTab.toUpperCase()}`}
              </h2>
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey={
                      chartData[0]?.frequency_ghz > 1
                        ? 'frequency_ghz'
                        : 'frequency_mhz'
                    }
                    label={{
                      value:
                        chartData[0]?.frequency_ghz > 1
                          ? 'Frequency (GHz)'
                          : 'Frequency (MHz)',
                      position: 'insideBottom',
                      offset: -5,
                    }}
                  />
                  <YAxis
                    label={{
                      value: 'Magnitude (dB)',
                      angle: -90,
                      position: 'insideLeft',
                    }}
                    domain={['auto', 0]}
                  />
                  <Tooltip
                    formatter={(value: number, name: string) => [
                      `${value.toFixed(2)} dB`,
                      name,
                    ]}
                    labelFormatter={(label: number) =>
                      `${label.toFixed(3)} ${chartData[0]?.frequency_ghz > 1 ? 'GHz' : 'MHz'}`
                    }
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="s11_db"
                    stroke="#e74c3c"
                    strokeWidth={2}
                    dot={false}
                    name="S11 (Return Loss)"
                  />
                  <Line
                    type="monotone"
                    dataKey="s21_db"
                    stroke="#3498db"
                    strokeWidth={2}
                    dot={false}
                    name="S21 (Insertion Loss)"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Overview: All Interfaces Summary */}
          {selectedInterfaceTab === 'all' && hasMultipleInterfaces && (
            <div className="card mb-3">
              <h2>Interface Summary</h2>
              <div className="grid grid-2" style={{ gap: '16px' }}>
                {Object.entries(interfaceResults).map(([ifaceType, iface]) => {
                  const colors = INTERFACE_COLORS[ifaceType] || {
                    primary: '#333',
                    secondary: '#f5f5f5',
                    icon: '📡',
                  };
                  const specs = getInterfaceSpecs(ifaceType);

                  if (!specs) return null;
                  if (specs.error)
                    return (
                      <div
                        key={ifaceType}
                        className="card"
                        style={{ borderLeft: `4px solid ${colors.primary}` }}
                      >
                        <h3>
                          {colors.icon} {ifaceType.toUpperCase()}
                        </h3>
                        <p style={{ color: '#d32f2f' }}>Error: {specs.error}</p>
                      </div>
                    );

                  return (
                    <div
                      key={ifaceType}
                      className="card"
                      style={{ borderLeft: `4px solid ${colors.primary}` }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                        }}
                      >
                        <div>
                          <h3 style={{ margin: 0 }}>
                            {colors.icon} {ifaceType.toUpperCase()}
                          </h3>
                          <p
                            className="text-muted"
                            style={{ margin: '4px 0', fontSize: '0.85rem' }}
                          >
                            {specs.description}
                          </p>
                        </div>
                        <span
                          style={{
                            padding: '4px 12px',
                            borderRadius: '12px',
                            backgroundColor: specs.overallPass
                              ? '#c8e6c9'
                              : '#ffcdd2',
                            color: specs.overallPass ? '#2e7d32' : '#c62828',
                            fontWeight: 600,
                            fontSize: '0.8rem',
                          }}
                        >
                          {specs.overallPass ? 'PASS' : 'REVIEW'}
                        </span>
                      </div>
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: '1fr 1fr 1fr',
                          gap: '8px',
                          marginTop: '12px',
                        }}
                      >
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
                            {specs.avg_impedance_ohm.toFixed(0)}Ω
                          </div>
                          <div style={{ fontSize: '0.75rem', color: '#888' }}>
                            Impedance
                          </div>
                        </div>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
                            {specs.return_loss_min_db?.toFixed(1)} dB
                          </div>
                          <div style={{ fontSize: '0.75rem', color: '#888' }}>
                            S11 min
                          </div>
                        </div>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
                            {specs.insertion_loss_max_db?.toFixed(1)} dB
                          </div>
                          <div style={{ fontSize: '0.75rem', color: '#888' }}>
                            S21 max
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => setSelectedInterfaceTab(ifaceType)}
                        style={{
                          marginTop: '12px',
                          padding: '6px 12px',
                          border: 'none',
                          borderRadius: '4px',
                          backgroundColor: colors.secondary,
                          color: colors.primary,
                          cursor: 'pointer',
                          width: '100%',
                        }}
                      >
                        View Details →
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Legacy Metrics (for non-interface results) */}
          {!hasMultipleInterfaces && metrics && (
            <div className="card mb-3">
              <h2>Computed Metrics</h2>
              <div className="grid grid-2">
                {metrics.return_loss && (
                  <div className="card">
                    <h3>Return Loss (S11)</h3>
                    <p className="text-small">
                      Min: {metrics.return_loss.min_db?.toFixed(2)} dB
                      <br />
                      Max: {metrics.return_loss.max_db?.toFixed(2)} dB
                      <br />
                      Mean: {metrics.return_loss.mean_db?.toFixed(2)} dB
                    </p>
                  </div>
                )}

                {metrics.insertion_loss && (
                  <div className="card">
                    <h3>Insertion Loss (S21)</h3>
                    <p className="text-small">
                      Min: {metrics.insertion_loss.min_db?.toFixed(2)} dB
                      <br />
                      Max: {metrics.insertion_loss.max_db?.toFixed(2)} dB
                      <br />
                      Mean: {metrics.insertion_loss.mean_db?.toFixed(2)} dB
                    </p>
                  </div>
                )}

                {metrics.bandwidth && metrics.bandwidth.widest_band && (
                  <div className="card">
                    <h3>Usable Bandwidth</h3>
                    <p className="text-small">
                      Start:{' '}
                      {(metrics.bandwidth.widest_band.start_hz / 1e6).toFixed(2)}{' '}
                      MHz
                      <br />
                      Stop:{' '}
                      {(metrics.bandwidth.widest_band.stop_hz / 1e6).toFixed(2)}{' '}
                      MHz
                      <br />
                      BW:{' '}
                      {(
                        metrics.bandwidth.widest_band.bandwidth_hz / 1e6
                      ).toFixed(2)}{' '}
                      MHz
                    </p>
                  </div>
                )}

                {metrics.resonances && metrics.resonances.length > 0 && (
                  <div className="card">
                    <h3>Resonances</h3>
                    <p className="text-small">
                      Found {metrics.resonances.length} resonance(s)
                    </p>
                    <ul className="text-small">
                      {metrics.resonances
                        .slice(0, 3)
                        .map((res: any, idx: number) => (
                          <li key={idx}>
                            {(res.frequency_hz / 1e6).toFixed(2)} MHz (S11:{' '}
                            {res.s11_db.toFixed(2)} dB)
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {run.status === 'failed' && (
        <div className="alert alert-error">
          Simulation failed: {run.error_message || 'Unknown error'}
        </div>
      )}

      {(run.status === 'running' || run.status === 'queued') && (
        <div className="alert alert-info">
          Simulation is {run.status}. Results will appear when complete.
        </div>
      )}
    </div>
  );
}
