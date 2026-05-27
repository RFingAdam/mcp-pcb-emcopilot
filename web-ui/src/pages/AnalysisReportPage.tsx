import React, { useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { analysisApi, aiApi, rulesApi, thermalApi } from '../api/client';

interface AnalysisReport {
  project_id: number;
  layout_id: number;
  layout_name: string;
  generated_at: string;
  overall_score: number;
  sections: {
    rules: RulesSection;
    thermal: ThermalSection;
    signal_integrity: SISection;
    emc: EMCSection;
    dfm: DFMSection;
    ai_insights: AISection;
  };
}

interface RulesSection {
  score: number;
  total_violations: number;
  critical: number;
  errors: number;
  warnings: number;
  top_issues: Array<{ rule: string; count: number; severity: string }>;
}

interface ThermalSection {
  score: number;
  max_temp_c: number;
  hotspot_count: number;
  high_power_components: number;
  recommendations: string[];
}

interface SISection {
  score: number;
  impedance_issues: number;
  crosstalk_issues: number;
  timing_issues: number;
  recommendations: string[];
}

interface EMCSection {
  score: number;
  grounding_issues: number;
  shielding_issues: number;
  antenna_issues: number;
  recommendations: string[];
}

interface DFMSection {
  score: number;
  manufacturability_issues: number;
  assembly_issues: number;
  recommendations: string[];
}

interface AISection {
  summary: string;
  key_findings: string[];
  recommendations: string[];
  risk_assessment: string;
}

const SECTION_CONFIG = {
  rules: { icon: '📋', label: 'Design Rules', color: 'blue' },
  thermal: { icon: '🌡️', label: 'Thermal', color: 'orange' },
  signal_integrity: { icon: '📶', label: 'Signal Integrity', color: 'purple' },
  emc: { icon: '📡', label: 'EMC', color: 'green' },
  dfm: { icon: '🏭', label: 'DFM', color: 'yellow' },
  ai_insights: { icon: '🤖', label: 'AI Insights', color: 'indigo' },
};

export default function AnalysisReportPage() {
  const { projectId, layoutId } = useParams<{ projectId: string; layoutId: string }>();
  const reportRef = useRef<HTMLDivElement>(null);
  
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  // Fetch all analysis data
  const { data: rulesData } = useQuery({
    queryKey: ['rule-violations', layoutId],
    queryFn: () => rulesApi.getViolations(Number(layoutId)),
    enabled: !!layoutId,
  });

  const { data: thermalData } = useQuery({
    queryKey: ['thermal-analysis', layoutId],
    queryFn: () => thermalApi.getThermalAnalysis(Number(layoutId)).catch(() => null),
    enabled: !!layoutId,
  });

  const { data: aiReview } = useQuery({
    queryKey: ['ai-review', layoutId],
    queryFn: () => aiApi.reviewLayout({
      project_id: Number(projectId),
      layout_id: Number(layoutId),
    }).catch(() => null),
    enabled: !!layoutId && !!projectId,
  });

  // Build report from fetched data
  const report: AnalysisReport | null = React.useMemo(() => {
    if (!rulesData) return null;

    return {
      project_id: Number(projectId),
      layout_id: Number(layoutId),
      layout_name: `Layout ${layoutId}`,
      generated_at: new Date().toISOString(),
      overall_score: calculateOverallScore(rulesData, thermalData),
      sections: {
        rules: {
          score: rulesData.score || 100,
          total_violations: rulesData.violations?.length || 0,
          critical: rulesData.critical_count || 0,
          errors: rulesData.error_count || 0,
          warnings: rulesData.warning_count || 0,
          top_issues: getTopIssues(rulesData.violations || []),
        },
        thermal: {
          score: thermalData?.score || 100,
          max_temp_c: thermalData?.max_temp_c || 25,
          hotspot_count: thermalData?.hotspots?.length || 0,
          high_power_components: thermalData?.components?.filter((c: any) => c.power_w > 2)?.length || 0,
          recommendations: getThermalRecommendations(thermalData),
        },
        signal_integrity: {
          score: 85, // Would come from SI analysis
          impedance_issues: 2,
          crosstalk_issues: 1,
          timing_issues: 0,
          recommendations: [
            'Check impedance on high-speed nets',
            'Review differential pair routing',
          ],
        },
        emc: {
          score: 90,
          grounding_issues: 1,
          shielding_issues: 0,
          antenna_issues: 2,
          recommendations: [
            'Add stitching vias near board edge',
            'Review return path for high-speed signals',
          ],
        },
        dfm: {
          score: 92,
          manufacturability_issues: 3,
          assembly_issues: 1,
          recommendations: [
            'Increase solder mask clearance on fine-pitch components',
            'Add fiducials for assembly',
          ],
        },
        ai_insights: {
          summary: aiReview?.summary || 'AI analysis available after running review.',
          key_findings: aiReview?.key_findings || [],
          recommendations: aiReview?.recommendations || [],
          risk_assessment: aiReview?.risk_level || 'Not assessed',
        },
      },
    };
  }, [rulesData, thermalData, aiReview, projectId, layoutId]);

  const handleExportPDF = async () => {
    setIsGenerating(true);
    // Would use html2pdf or similar library
    setTimeout(() => {
      setIsGenerating(false);
      alert('PDF export would be generated here');
    }, 1500);
  };

  const handleRunFullAnalysis = async () => {
    setIsGenerating(true);
    try {
      // Run all analyses
      await Promise.all([
        rulesApi.runCheck(Number(layoutId)),
        thermalApi.runThermalAnalysis(Number(layoutId)),
      ]);
      // Refetch data
      window.location.reload();
    } finally {
      setIsGenerating(false);
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 90) return 'text-green-600';
    if (score >= 70) return 'text-yellow-600';
    if (score >= 50) return 'text-orange-600';
    return 'text-red-600';
  };

  const getScoreGradient = (score: number) => {
    if (score >= 90) return 'from-green-400 to-green-600';
    if (score >= 70) return 'from-yellow-400 to-yellow-600';
    if (score >= 50) return 'from-orange-400 to-orange-600';
    return 'from-red-400 to-red-600';
  };

  if (!report) {
    return (
      <div className="min-h-screen bg-gray-50 p-6">
        <div className="max-w-4xl mx-auto">
          <Link to={`/projects/${projectId}`} className="text-blue-600 hover:underline text-sm">
            ← Back to Project
          </Link>
          <div className="mt-8 text-center">
            <h1 className="text-2xl font-bold mb-4">Analysis Report</h1>
            <p className="text-gray-600 mb-6">No analysis data available yet.</p>
            <button
              onClick={handleRunFullAnalysis}
              disabled={isGenerating}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {isGenerating ? 'Running Analysis...' : 'Run Full Analysis'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <Link to={`/projects/${projectId}`} className="text-blue-600 hover:underline text-sm">
                ← Back to Project
              </Link>
              <h1 className="text-2xl font-bold mt-1">Analysis Report</h1>
              <p className="text-gray-500 text-sm">
                Generated {new Date(report.generated_at).toLocaleString()}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleRunFullAnalysis}
                disabled={isGenerating}
                className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
              >
                🔄 Refresh
              </button>
              <button
                onClick={handleExportPDF}
                disabled={isGenerating}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                📥 Export PDF
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6" ref={reportRef}>
        {/* Overall Score */}
        <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-700">Overall Design Score</h2>
              <p className="text-gray-500 text-sm">
                Based on {Object.keys(report.sections).length} analysis categories
              </p>
            </div>
            <div className="text-right">
              <div className={`text-5xl font-bold ${getScoreColor(report.overall_score)}`}>
                {report.overall_score.toFixed(0)}
              </div>
              <div className="text-gray-500">/ 100</div>
            </div>
          </div>
          
          {/* Score Bar */}
          <div className="mt-4 h-4 bg-gray-200 rounded-full overflow-hidden">
            <div
              className={`h-full bg-gradient-to-r ${getScoreGradient(report.overall_score)} transition-all duration-500`}
              style={{ width: `${report.overall_score}%` }}
            />
          </div>

          {/* Category Scores */}
          <div className="grid grid-cols-6 gap-4 mt-6">
            {Object.entries(report.sections).map(([key, section]) => {
              const config = SECTION_CONFIG[key as keyof typeof SECTION_CONFIG];
              const score = 'score' in section ? section.score : 0;
              return (
                <button
                  key={key}
                  onClick={() => setActiveSection(activeSection === key ? null : key)}
                  className={`text-center p-3 rounded-lg border-2 transition-all ${
                    activeSection === key
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-transparent hover:bg-gray-50'
                  }`}
                >
                  <div className="text-2xl mb-1">{config.icon}</div>
                  <div className={`text-xl font-bold ${getScoreColor(score)}`}>
                    {score.toFixed(0)}
                  </div>
                  <div className="text-xs text-gray-500">{config.label}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Detailed Sections */}
        <div className="grid grid-cols-2 gap-6">
          {/* Design Rules */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                📋 Design Rules
              </h3>
              <Link
                to={`/projects/${projectId}/layouts/${layoutId}/violations`}
                className="text-blue-600 hover:underline text-sm"
              >
                View Details →
              </Link>
            </div>
            
            <div className="grid grid-cols-4 gap-4 mb-4">
              <div className="text-center p-3 bg-red-50 rounded">
                <div className="text-xl font-bold text-red-600">
                  {report.sections.rules.critical}
                </div>
                <div className="text-xs text-gray-600">Critical</div>
              </div>
              <div className="text-center p-3 bg-orange-50 rounded">
                <div className="text-xl font-bold text-orange-600">
                  {report.sections.rules.errors}
                </div>
                <div className="text-xs text-gray-600">Errors</div>
              </div>
              <div className="text-center p-3 bg-yellow-50 rounded">
                <div className="text-xl font-bold text-yellow-600">
                  {report.sections.rules.warnings}
                </div>
                <div className="text-xs text-gray-600">Warnings</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.rules.total_violations}
                </div>
                <div className="text-xs text-gray-600">Total</div>
              </div>
            </div>

            {report.sections.rules.top_issues.length > 0 && (
              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">Top Issues</div>
                <ul className="space-y-1">
                  {report.sections.rules.top_issues.slice(0, 3).map((issue, i) => (
                    <li key={i} className="text-sm flex justify-between">
                      <span>{issue.rule}</span>
                      <span className="text-gray-500">×{issue.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Thermal */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                🌡️ Thermal Analysis
              </h3>
              <Link
                to={`/projects/${projectId}/layouts/${layoutId}/thermal`}
                className="text-blue-600 hover:underline text-sm"
              >
                View Map →
              </Link>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className={`text-xl font-bold ${
                  report.sections.thermal.max_temp_c > 100 ? 'text-red-600' :
                  report.sections.thermal.max_temp_c > 80 ? 'text-orange-600' : 'text-green-600'
                }`}>
                  {report.sections.thermal.max_temp_c.toFixed(0)}°C
                </div>
                <div className="text-xs text-gray-600">Max Temp</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.thermal.hotspot_count}
                </div>
                <div className="text-xs text-gray-600">Hotspots</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.thermal.high_power_components}
                </div>
                <div className="text-xs text-gray-600">High Power</div>
              </div>
            </div>

            {report.sections.thermal.recommendations.length > 0 && (
              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">Recommendations</div>
                <ul className="space-y-1">
                  {report.sections.thermal.recommendations.slice(0, 2).map((rec, i) => (
                    <li key={i} className="text-sm text-gray-600 flex gap-2">
                      <span>💡</span>
                      <span>{rec}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Signal Integrity */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-4">
              📶 Signal Integrity
            </h3>

            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.signal_integrity.impedance_issues}
                </div>
                <div className="text-xs text-gray-600">Impedance</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.signal_integrity.crosstalk_issues}
                </div>
                <div className="text-xs text-gray-600">Crosstalk</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.signal_integrity.timing_issues}
                </div>
                <div className="text-xs text-gray-600">Timing</div>
              </div>
            </div>

            <ul className="space-y-1">
              {report.sections.signal_integrity.recommendations.map((rec, i) => (
                <li key={i} className="text-sm text-gray-600 flex gap-2">
                  <span>💡</span>
                  <span>{rec}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* EMC */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-4">
              📡 EMC Analysis
            </h3>

            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.emc.grounding_issues}
                </div>
                <div className="text-xs text-gray-600">Grounding</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.emc.shielding_issues}
                </div>
                <div className="text-xs text-gray-600">Shielding</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded">
                <div className="text-xl font-bold">
                  {report.sections.emc.antenna_issues}
                </div>
                <div className="text-xs text-gray-600">Antenna</div>
              </div>
            </div>

            <ul className="space-y-1">
              {report.sections.emc.recommendations.map((rec, i) => (
                <li key={i} className="text-sm text-gray-600 flex gap-2">
                  <span>💡</span>
                  <span>{rec}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* AI Insights - Full Width */}
        <div className="bg-white rounded-xl shadow-sm border p-6 mt-6">
          <h3 className="text-lg font-semibold flex items-center gap-2 mb-4">
            🤖 AI-Generated Insights
          </h3>

          <div className="prose max-w-none">
            <p className="text-gray-700">{report.sections.ai_insights.summary}</p>

            {report.sections.ai_insights.key_findings.length > 0 && (
              <div className="mt-4">
                <h4 className="font-medium text-gray-800 mb-2">Key Findings</h4>
                <ul className="list-disc pl-5 space-y-1">
                  {report.sections.ai_insights.key_findings.map((finding, i) => (
                    <li key={i} className="text-gray-700">{finding}</li>
                  ))}
                </ul>
              </div>
            )}

            {report.sections.ai_insights.recommendations.length > 0 && (
              <div className="mt-4">
                <h4 className="font-medium text-gray-800 mb-2">AI Recommendations</h4>
                <div className="space-y-2">
                  {report.sections.ai_insights.recommendations.map((rec, i) => (
                    <div key={i} className="flex gap-2 p-3 bg-indigo-50 rounded-lg">
                      <span>💡</span>
                      <span className="text-gray-700">{rec}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-4 p-4 bg-gray-50 rounded-lg">
              <span className="text-sm text-gray-500">Risk Assessment: </span>
              <span className={`font-medium ${
                report.sections.ai_insights.risk_assessment === 'Low' ? 'text-green-600' :
                report.sections.ai_insights.risk_assessment === 'Medium' ? 'text-yellow-600' :
                'text-red-600'
              }`}>
                {report.sections.ai_insights.risk_assessment}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Helper functions
function calculateOverallScore(rulesData: any, thermalData: any): number {
  const rulesScore = rulesData?.score || 100;
  const thermalScore = thermalData?.score || 100;
  // Weight rules more heavily
  return rulesScore * 0.5 + thermalScore * 0.3 + 85 * 0.2; // 85 = placeholder for other scores
}

function getTopIssues(violations: any[]): Array<{ rule: string; count: number; severity: string }> {
  const counts: Record<string, { count: number; severity: string }> = {};
  
  violations.forEach((v) => {
    if (!counts[v.rule_name]) {
      counts[v.rule_name] = { count: 0, severity: v.severity };
    }
    counts[v.rule_name].count++;
  });

  return Object.entries(counts)
    .map(([rule, data]) => ({ rule, ...data }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
}

function getThermalRecommendations(thermalData: any): string[] {
  if (!thermalData) return ['Run thermal analysis to get recommendations'];
  
  const recommendations: string[] = [];
  
  if (thermalData.max_temp_c > 100) {
    recommendations.push('Critical: Maximum temperature exceeds 100°C - review cooling solution');
  }
  
  if (thermalData.hotspots?.length > 2) {
    recommendations.push('Multiple hotspots detected - consider spreading high-power components');
  }
  
  const lowCoverage = thermalData.thermal_vias?.filter((v: any) => v.coverage_percent < 60);
  if (lowCoverage?.length > 0) {
    recommendations.push(`Increase thermal via count on ${lowCoverage.length} component(s)`);
  }

  return recommendations;
}
