import { useState, useEffect } from 'react';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import apiClient, { projectsApi, agentApi, PCBLayout } from '../api/client';

export default function AIReviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const layoutId = searchParams.get('layoutId');

  const [selectedLayoutId, setSelectedLayoutId] = useState<number | null>(
    layoutId ? Number(layoutId) : null
  );
  const [context, setContext] = useState('');
  const [review, setReview] = useState<any>(null);
  const [isReviewing, setIsReviewing] = useState(false);
  const [isImproving, setIsImproving] = useState(false);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [reviewStatus, setReviewStatus] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  // Model selection state
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [optimizationMode, setOptimizationMode] = useState<string>('auto');
  const [detailLevel, setDetailLevel] = useState<string>('standard');
  const [useMultiPass, setUseMultiPass] = useState<boolean>(false);

  const { data: layouts } = useQuery({
    queryKey: ['layouts', projectId],
    queryFn: () => projectsApi.listLayouts(Number(projectId)),
  });

  const handleImproveContext = async () => {
    if (!context.trim()) return;
    setIsImproving(true);
    try {
      const response = await apiClient.post('/ai/prompt/improve', {
        current_text: context,
        project_id: projectId ? Number(projectId) : undefined,
        layout_id: selectedLayoutId || undefined
      });
      if (response.data && response.data.improved_text) {
        setContext(response.data.improved_text);
      }
    } catch (error) {
      console.error("Failed to improve prompt:", error);
    } finally {
      setIsImproving(false);
    }
  };

  const handleReview = async () => {
    if (!selectedLayoutId) return;

    setIsReviewing(true);
    setReviewStatus(null);
    setReview(null);
    setError(null);

    try {
      // Build review options
      const options: any = {
        detail_level: detailLevel,
        include_correlations: true,
        output_formats: ['json', 'html'],
      };

      // Add model preferences based on optimization mode
      if (optimizationMode === 'quality') {
        options.prefer_codex = true;
        options.prefer_cost_efficiency = false;
        options.prefer_speed = false;
      } else if (optimizationMode === 'speed') {
        options.prefer_codex = false;
        options.prefer_cost_efficiency = false;
        options.prefer_speed = true;
      } else if (optimizationMode === 'cost') {
        options.prefer_codex = false;
        options.prefer_cost_efficiency = true;
        options.prefer_speed = false;
      } else {
        // Auto mode
        options.prefer_codex = true;
      }

      // Explicit model override
      if (selectedModel) {
        options.model = selectedModel;
      }

      // Multi-pass analysis
      options.use_multi_pass = useMultiPass;

      // Start autonomous review
      const result = await agentApi.startReview(selectedLayoutId, options);
      setReviewId(result.review_id);
    } catch (err: any) {
      console.error('Review failed to start:', err);
      const errorMessage = err?.response?.data?.detail
        || err?.message
        || 'Failed to start review. Please check that the backend services are running.';
      setError(errorMessage);
      setIsReviewing(false);
    }
  };

  // Poll for review status
  useEffect(() => {
    if (!reviewId || !isReviewing) return;

    const pollInterval = setInterval(async () => {
      try {
        const status = await agentApi.getReviewStatus(reviewId);
        setReviewStatus(status);

        if (status.status === 'completed') {
          // Fetch final results
          const results = await agentApi.getReviewResults(reviewId);
          setReview(results);
          setIsReviewing(false);
          clearInterval(pollInterval);
        } else if (status.status === 'failed') {
          setError(status.error || 'Review failed. Check backend logs for details.');
          setIsReviewing(false);
          clearInterval(pollInterval);
        } else if (status.status === 'timeout') {
          setError('Review timed out. The analysis took too long to complete.');
          setIsReviewing(false);
          clearInterval(pollInterval);
        }
      } catch (err: any) {
        console.error('Failed to poll status:', err);
        // After several failed polls, show error to user
        const errorMessage = err?.response?.data?.detail || err?.message || 'Lost connection to server';
        setError(`Status check failed: ${errorMessage}`);
        setIsReviewing(false);
        clearInterval(pollInterval);
      }
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(pollInterval);
  }, [reviewId, isReviewing]);

  return (
    <div>
      <div className="mb-3">
        <Link to={`/projects/${projectId}`} className="btn btn-secondary">
          ← Back to Project
        </Link>
      </div>

      <div className="card mb-3">
        <h1>AI-Powered PCB Layout Review</h1>
        <p className="text-muted">
          Get intelligent analysis and recommendations for your PCB design
        </p>
      </div>

      <div className="card mb-3">
        <h2>Configure Review</h2>

        <div className="form-group">
          <label>Layout to Review</label>
          <select
            className="form-control"
            value={selectedLayoutId || ''}
            onChange={(e) => setSelectedLayoutId(Number(e.target.value) || null)}
          >
            <option value="">Select a layout...</option>
            {layouts?.map((layout: PCBLayout) => (
              <option key={layout.id} value={layout.id}>
                {layout.layout_name} ({layout.file_type})
              </option>
            ))}
          </select>
          {layouts && layouts.length === 0 && (
            <small className="text-warning">
              No layouts found. Please upload a PCB layout file first.
            </small>
          )}
        </div>

        <div className="grid grid-3">
          <div className="form-group">
            <label>AI Model</label>
            <select
              className="form-control"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              <option value="">Auto (Recommended)</option>
              <optgroup label="Flagship Codex Models (Best for PCB Analysis)">
                <option value="gpt-5.2-codex">GPT-5.2 Codex - Flagship, 200K context</option>
                <option value="gpt-5.1-codex-max">GPT-5.1 Codex Max - Extended reasoning</option>
                <option value="gpt-5.1-codex">GPT-5.1 Codex - High performance</option>
                <option value="gpt-5.1-codex-mini">GPT-5.1 Codex Mini - Fast analysis</option>
              </optgroup>
              <optgroup label="General Purpose GPT-5 Models">
                <option value="gpt-5.2">GPT-5.2 - 400K context, flagship</option>
                <option value="gpt-5.1">GPT-5.1 - High performance</option>
                <option value="gpt-5-mini">GPT-5 Mini - Balanced</option>
                <option value="gpt-5-nano">GPT-5 Nano - Ultra-fast</option>
              </optgroup>
              <optgroup label="Cost-Efficient Models">
                <option value="gpt-4.1">GPT-4.1 - Great value</option>
                <option value="gpt-4.1-mini">GPT-4.1 Mini - Budget-friendly</option>
                <option value="gpt-4.1-nano">GPT-4.1 Nano - Minimal cost</option>
              </optgroup>
              <optgroup label="Reasoning Models">
                <option value="o3">o3 - Advanced reasoning</option>
                <option value="o3-deep-research">o3 Deep Research - Extended analysis</option>
                <option value="o4-mini-deep-research">o4 Mini Deep Research - Fast reasoning</option>
              </optgroup>
              <optgroup label="Claude Models (Alternative)">
                <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
                <option value="claude-3-opus-20240229">Claude 3 Opus</option>
                <option value="claude-3-haiku-20240307">Claude 3 Haiku - Fast</option>
              </optgroup>
            </select>
            <small className="text-muted">
              Codex models excel at engineering analysis with high reasoning
            </small>
            {selectedModel && (
              <div className="mt-1" style={{
                padding: '0.5rem',
                background: '#f0f4f8',
                borderRadius: '4px',
                fontSize: '0.85rem'
              }}>
                <strong>Selected:</strong> {selectedModel}
                {selectedModel.includes('codex') && (
                  <span style={{ color: '#22c55e', marginLeft: '0.5rem' }}>
                    Optimized for PCB analysis
                  </span>
                )}
                {selectedModel.includes('gpt-5.2') && (
                  <span style={{ color: '#3b82f6', marginLeft: '0.5rem' }}>
                    Flagship Model
                  </span>
                )}
                {selectedModel.includes('claude') && (
                  <span style={{ color: '#8b5cf6', marginLeft: '0.5rem' }}>
                    Anthropic Alternative
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="form-group">
            <label>Optimization</label>
            <select
              className="form-control"
              value={optimizationMode}
              onChange={(e) => setOptimizationMode(e.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="quality">Quality (Best Results)</option>
              <option value="speed">Speed (Faster)</option>
              <option value="cost">Cost (Cheaper)</option>
            </select>
          </div>

          <div className="form-group">
            <label>Detail Level</label>
            <select
              className="form-control"
              value={detailLevel}
              onChange={(e) => setDetailLevel(e.target.value)}
            >
              <option value="quick">Quick</option>
              <option value="standard">Standard</option>
              <option value="detailed">Detailed</option>
              <option value="exhaustive">Exhaustive</option>
            </select>
          </div>
        </div>

        <div className="form-group mt-2">
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={useMultiPass}
              onChange={(e) => setUseMultiPass(e.target.checked)}
              style={{ width: '18px', height: '18px' }}
            />
            <span>Enable Multi-Pass Analysis</span>
            <span className="badge badge-info" style={{ marginLeft: '0.5rem' }}>Premium</span>
          </label>
          <small className="text-muted" style={{ display: 'block', marginTop: '0.25rem' }}>
            3-pass analysis: Quick scan (gpt-4.1-nano) → Deep analysis (gpt-5.1-codex) → Expert validation (gpt-5.2-codex).
            Provides higher accuracy with expert-validated findings.
          </small>
        </div>

        <div className="form-group">
          <label>Additional Context (Optional)</label>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
            <textarea
              className="form-control"
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="e.g., High-speed USB 3.0 design, needs EMI compliance"
              rows={2}
              style={{ flex: 1 }}
            />
            <button 
              className="btn btn-secondary"
              onClick={handleImproveContext}  
              disabled={isImproving || !context}
              style={{ whiteSpace: 'nowrap' }}
            >
              {isImproving ? 'Thinking...' : '✨ AI Improve'}
            </button>
          </div>
          <small className="text-muted">
            Click 'AI Improve' to enhance your description for better analysis targeting.
          </small>
        </div>

        <button
          className="btn btn-primary"
          onClick={handleReview}
          disabled={!selectedLayoutId || isReviewing}
        >
          {isReviewing ? 'Analyzing...' : 'Start Autonomous Review'}
        </button>

        {isReviewing && reviewStatus && (
          <div className="alert alert-info mt-2">
            <strong>Status:</strong> {reviewStatus.phase || 'Starting'}
            {reviewStatus.progress > 0 && ` - ${reviewStatus.progress}% complete`}
            {reviewStatus.message && <><br/>{reviewStatus.message}</>}
          </div>
        )}

        {error && (
          <div className="alert alert-error mt-2">
            <strong>Error:</strong> {error}
            <br/>
            <small>Make sure the Celery worker is running. Check the console for more details.</small>
          </div>
        )}
      </div>

      {review && (
        <div>
          <div className="card mb-3">
            <div className="flex-between mb-2">
              <h2>Review Complete</h2>
              {review.overall_grade && (
                <span className={`badge badge-${
                  review.overall_grade === 'A' ? 'success' :
                  review.overall_grade === 'B' ? 'info' :
                  review.overall_grade === 'C' ? 'warning' : 'error'
                }`} style={{ fontSize: '1.5rem' }}>
                  Grade: {review.overall_grade}
                </span>
              )}
            </div>

            {review.classification && (
              <div className="mb-2">
                <h3>Design Classification</h3>
                <p>
                  <strong>Type:</strong> {review.classification.design_type || 'Unknown'}<br />
                  <strong>Complexity:</strong> {review.classification.complexity || 'Unknown'}<br />
                  {review.classification.confidence && (
                    <><strong>Confidence:</strong> {(review.classification.confidence * 100).toFixed(0)}%<br /></>
                  )}
                </p>
              </div>
            )}

            <div className="grid grid-3 mt-2">
              <div>
                <strong>Total Findings:</strong> {review.findings_count || 0}
              </div>
              <div>
                <strong>Correlations:</strong> {review.correlations_count || 0}
              </div>
              <div>
                <strong>Review ID:</strong> <code className="text-small">{review.review_id}</code>
              </div>
            </div>
          </div>

          {review.scores && (
            <div className="card mb-3">
              <h2>Category Scores</h2>
              <div className="grid grid-3">
                {Object.entries(review.scores).map(([category, score]: [string, any]) => (
                  <div key={category} className="card">
                    <h3 className="text-small">{category.replace(/_/g, ' ').toUpperCase()}</h3>
                    <div className="flex-between">
                      <span style={{ fontSize: '2rem', fontWeight: 'bold' }}>{score}</span>
                      <span className={`badge badge-${
                        score >= 90 ? 'success' :
                        score >= 70 ? 'info' :
                        score >= 50 ? 'warning' : 'error'
                      }`}>
                        {score >= 90 ? 'Excellent' :
                         score >= 70 ? 'Good' :
                         score >= 50 ? 'Fair' : 'Needs Improvement'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="card">
            <div className="flex-between mb-2">
              <h2>View Detailed Results</h2>
              <div>
                {review.report_path && (
                  <a
                    href={`/api/v1/agent/review/${review.review_id}/report?format=html`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-secondary btn-sm mr-2"
                  >
                    📄 HTML Report
                  </a>
                )}
                <Link
                  to={`/reviews/${review.review_id}/findings${selectedLayoutId ? `?layoutId=${selectedLayoutId}` : ''}`}
                  className="btn btn-primary btn-sm"
                >
                  🔍 View All Findings ({review.findings_count || 0})
                </Link>
              </div>
            </div>
            <p className="text-muted">
              The autonomous review has completed. Use the buttons above to access detailed findings,
              correlations, and comprehensive reports.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
