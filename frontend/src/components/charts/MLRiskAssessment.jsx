import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer } from 'recharts';

export default function MLRiskAssessment({ analytics }) {
  if (!analytics) return null;

  const data = [
    { name: 'High', Probability: analytics.risk_probabilities?.High || 0 },
    { name: 'Low', Probability: analytics.risk_probabilities?.Low || 0 },
    { name: 'Medium', Probability: analytics.risk_probabilities?.Medium || 0 },
  ];

  const getRiskColor = (level) => {
    switch (level) {
      case 'High': return '#ef4444';
      case 'Medium': return '#eab308';
      case 'Low': return '#22c55e';
      default: return '#64748b';
    }
  };

  return (
    <div className="bg-card border border-gray-800 p-6 rounded-lg mb-8">
      <div className="mb-4">
        <h2 className="text-xl font-bold flex items-center gap-2 text-white">
          <span>🤖</span> ML Risk Assessment
        </h2>
        <p className="text-xs text-muted mt-2">
          Predicted by a RandomForest model trained on synthetic loan data — estimates affordability risk from the same inputs above. 
        </p>
      </div>

      <div className="flex items-center gap-3 mb-8">
        <span className="text-lg font-semibold text-white">Predicted Risk Level:</span>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded-full" style={{ backgroundColor: getRiskColor(analytics.risk_label) }}></div>
          <span className="text-lg font-bold text-white">{analytics.risk_label}</span>
        </div>
      </div>

      <div className="h-64">
        <p className="text-sm font-semibold text-gray-300 mb-4">Model Confidence by Risk Category</p>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="name" stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
            <YAxis stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} domain={[0, 1]} />
            <Bar dataKey="Probability" fill="#7dd3fc" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
