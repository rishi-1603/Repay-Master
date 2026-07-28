import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

export default function EMIChart({ loans }) {
  return (
    <div className="bg-white p-6 rounded-2xl shadow-sm border mt-8">
      <h2 className="text-xl font-semibold text-gray-800 mb-6">EMI Forecast Visualization</h2>
      <div className="h-64">
        {loans.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={loans}>
              <XAxis dataKey="title" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="monthly_emi" fill="#1E3A8A" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex items-center justify-center text-gray-400">Add a loan to view charts</div>
        )}
      </div>
    </div>
  );
}
