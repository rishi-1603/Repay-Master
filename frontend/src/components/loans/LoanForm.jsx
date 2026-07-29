import React, { useState } from 'react';
import { Building2, PlusCircle, AlertCircle } from 'lucide-react';

export default function LoanForm({ onCreateLoan }) {
  const [formData, setFormData] = useState({
    title: 'Personal Loan',
    principal: 2000000,
    annual_interest_rate: 8.5,
    tenure_months: 240,
    monthly_income: 100000,
    monthly_expenses: 40000,
    currency: 'INR'
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    onCreateLoan(formData);
  };

  const handleChange = (e) => {
    const value = e.target.type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value;
    setFormData({ ...formData, [e.target.name]: value });
  };

  return (
    <div className="bg-card border-b border-gray-800 p-8 shadow-md rounded-lg mb-8 text-white">
      <div className="flex items-center gap-3 mb-6">
        <Building2 className="text-primary" size={28} />
        <h1 className="text-2xl font-bold">RepayMaster — Loan Repayment Timeline Predictor</h1>
      </div>
      <p className="text-sm text-muted mb-8">EMI calculator + ML-based affordability risk predictor</p>

      <form onSubmit={handleSubmit}>
        <div className="mb-6">
          <label className="text-sm text-gray-400 mb-2 block">Select Currency ⓘ</label>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="currency" value="USD" checked={formData.currency === 'USD'} onChange={handleChange} className="accent-primary" />
              USD ($)
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="currency" value="INR" checked={formData.currency === 'INR'} onChange={handleChange} className="accent-primary" />
              INR (₹)
            </label>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
          <div>
            <h3 className="font-semibold text-lg mb-4 flex items-center gap-2">Loan Details</h3>
            
            <div className="space-y-4">
              <div>
                <label className="text-sm text-gray-400 block mb-1">Loan Amount ({formData.currency === 'INR' ? '₹' : '$'})</label>
                <input type="number" name="principal" value={formData.principal} onChange={handleChange} className="w-full bg-dark border border-gray-700 rounded p-2 text-white outline-none focus:border-primary" />
              </div>

              <div>
                <label className="text-sm text-gray-400 block mb-1">Interest Rate (%)</label>
                <input type="range" name="annual_interest_rate" min="1" max="20" step="0.1" value={formData.annual_interest_rate} onChange={handleChange} className="w-full accent-red-500" />
                <div className="text-center text-xs text-red-500 mt-1">{formData.annual_interest_rate}</div>
              </div>

              <div>
                <label className="text-sm text-gray-400 block mb-1">Tenure (Months)</label>
                <input type="number" name="tenure_months" value={formData.tenure_months} onChange={handleChange} className="w-full bg-dark border border-gray-700 rounded p-2 text-white outline-none focus:border-primary" />
              </div>
            </div>
          </div>

          <div>
            <h3 className="font-semibold text-lg mb-4 flex items-center gap-2">Financial Information</h3>
            
            <div className="space-y-4">
              <div>
                <label className="text-sm text-gray-400 block mb-1">Monthly Income ({formData.currency === 'INR' ? '₹' : '$'})</label>
                <input type="number" name="monthly_income" value={formData.monthly_income} onChange={handleChange} className="w-full bg-dark border border-gray-700 rounded p-2 text-white outline-none focus:border-primary" />
              </div>

              <div>
                <label className="text-sm text-gray-400 block mb-1">Monthly Expenses ({formData.currency === 'INR' ? '₹' : '$'})</label>
                <input type="number" name="monthly_expenses" value={formData.monthly_expenses} onChange={handleChange} className="w-full bg-dark border border-gray-700 rounded p-2 text-white outline-none focus:border-primary" />
              </div>
            </div>
          </div>
        </div>

        <div className="mt-8 bg-[#0c1a2f] border border-blue-900 rounded p-3 text-sm text-blue-300 flex items-center gap-2">
          <span className="bg-blue-600 text-white text-xs px-2 py-0.5 rounded font-bold">IN</span>
          Indian Rupee mode — amounts displayed in ₹. Large values shown in Lakhs (L) and Crores (Cr).
        </div>

        <button type="submit" className="mt-6 bg-red-500 hover:bg-red-600 text-white px-6 py-2 rounded font-medium transition-colors">
          Calculate Repayment Options
        </button>
      </form>
    </div>
  );
}
