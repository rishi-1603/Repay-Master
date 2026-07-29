import React from 'react';

export default function Recommendations({ analytics, currency }) {
  if (!analytics) return null;

  return (
    <div className="space-y-6 mb-8">
      
      {/* Milestone */}
      <div className="bg-[#1e293b] border border-blue-900 rounded-lg p-4 text-blue-300 text-sm flex items-center gap-2">
        <span className="font-semibold">Quarter Year Milestone 🌱</span> — unlocks in {Math.max(1, Math.floor(analytics.emi_scenarios?.[1]?.amount / 1000))} months (predictive estimate)
      </div>

      {/* Recommendations */}
      <div className="bg-card border border-gray-800 rounded-lg p-6">
        <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
          <span>💡</span> Recommendations
        </h2>
        {analytics.risk_label === 'High' ? (
          <div className="bg-red-900/30 border border-red-800 text-red-400 p-3 rounded flex items-center gap-2">
            ⚠️ This loan has a high risk profile. Consider increasing down payment or extending tenure.
          </div>
        ) : (
          <div className="bg-green-900/30 border border-green-800 text-green-400 p-3 rounded flex items-center gap-2">
            ✅ This loan is within your affordable range.
          </div>
        )}
      </div>

      {/* India Specific Tips - Only show if currency is INR */}
      {currency === 'INR' && (
        <div className="bg-card border border-gray-800 rounded-lg p-6">
          <h2 className="text-xl font-bold text-white mb-6">IN India-Specific Tips</h2>
          
          <div className="bg-[#0f172a] rounded p-6 text-blue-200">
            <h4 className="font-bold mb-3 text-blue-400">Tax Benefits:</h4>
            <ul className="list-disc list-inside space-y-2 mb-6 text-sm">
              <li>Section 24(b): Home loan interest deduction up to ₹2 L/year</li>
              <li>Section 80C: Principal repayment deduction up to ₹1.5 L/year</li>
              <li>PMAY / CLSS: First-time buyers may get interest subsidy under Pradhan Mantri Awas Yojana</li>
            </ul>

            <h4 className="font-bold mb-3 text-blue-400">Smart Repayment:</h4>
            <ul className="list-disc list-inside space-y-2 text-sm">
              <li>Even ₹5,000–₹10,000 extra per month as prepayment can cut your tenure by years</li>
              <li>Compare EAR (Effective Annual Rate), not just the headline rate, across banks</li>
              <li>SBI, HDFC, ICICI home loan rates typically range 8.5%–9.5% — negotiate!</li>
            </ul>
          </div>
        </div>
      )}

    </div>
  );
}
