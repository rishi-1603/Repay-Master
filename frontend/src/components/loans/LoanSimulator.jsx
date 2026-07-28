import React from 'react';
import { Calculator } from 'lucide-react';
import { compareBanks, optimizePrepayment } from '../../services/api';

export default function LoanSimulator({ loans }) {
  if (loans.length === 0) return null;

  const handleCompare = async () => {
    try {
      const res = await compareBanks(loans[0].principal, loans[0].tenure_months);
      alert(JSON.stringify(res, null, 2));
    } catch (e) {
      alert("Error comparing banks");
    }
  };

  const handleOptimize = async () => {
    try {
      const res = await optimizePrepayment(loans[0].principal, loans[0].annual_interest_rate, loans[0].tenure_months, 500);
      alert(`By paying an extra $500/month, you save $${res.total_savings} and finish ${res.months_saved} months early!`);
    } catch (e) {
      alert("Error optimizing prepayment");
    }
  };

  return (
    <div className="bg-white p-6 rounded-2xl shadow-sm border mt-8">
      <h2 className="text-xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
        <Calculator size={20} className="text-primary"/> Loan Comparison & What-If Simulator
      </h2>
      <p className="text-sm text-gray-500 mb-4">Select a loan to compare against top banks and calculate prepayment savings.</p>
      
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="p-4 bg-gray-50 rounded-lg border">
          <h3 className="font-medium text-gray-800 mb-2">Market Comparison</h3>
          <button onClick={handleCompare} className="text-sm bg-white border px-3 py-2 rounded shadow-sm hover:bg-gray-100 w-full text-left transition-colors">
            Compare your ${loans[0].principal.toLocaleString()} loan against HDFC, SBI, ICICI...
          </button>
        </div>
        <div className="p-4 bg-gray-50 rounded-lg border">
          <h3 className="font-medium text-gray-800 mb-2">Prepayment Optimizer</h3>
          <button onClick={handleOptimize} className="text-sm bg-white border px-3 py-2 rounded shadow-sm hover:bg-gray-100 w-full text-left transition-colors">
            Simulate paying an extra $500/month
          </button>
        </div>
      </div>
    </div>
  );
}
