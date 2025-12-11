import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage1.css';

export default function Stage1({ responses, contextSources = [] }) {
  const [activeTab, setActiveTab] = useState(0);
  const hasContext = contextSources.length > 0;

  if (!responses || responses.length === 0) {
    return null;
  }

  return (
    <div className="stage stage1">
      <h3 className="stage-title">Stage 1: Individual Responses</h3>

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {resp.model.split('/')[1] || resp.model}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="model-name">{responses[activeTab].model}</div>
        <div className="response-text markdown-content">
          <ReactMarkdown>{responses[activeTab].response}</ReactMarkdown>
        </div>

        {hasContext && (
          <details className="context-panel">
            <summary>
              Context Sources ({contextSources.length})
            </summary>
            <div className="context-list">
              {contextSources.map((source, index) => (
                <div key={index} className="context-item">
                  <div className="context-header">
                    <span className="context-label">Source #{index + 1}</span>
                    <span className="context-meta">
                      {source.published_at || 'Unknown date'}
                    </span>
                  </div>
                  <div className="context-title">
                    {source.title || 'Untitled'} &mdash; {source.source || 'Unknown outlet'}
                  </div>
                  {source.summary && (
                    <p className="context-summary">{source.summary}</p>
                  )}
                  {source.url && (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="context-link"
                    >
                      Read original article
                    </a>
                  )}
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
