import React from 'react';
import { PlusCircle, FileDown } from 'lucide-react';

export default function LoanTable({ loans, onAddDemo, onDownloadPdf }) {
  return (
    <div className="bg-white p-6 rounded-2xl shadow-sm border">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-semibold text-gray-800">Your Active Loans</h2>
        <button onClick={onAddDemo} className="flex items-center gap-2 text-sm bg-primary text-white px-4 py-2 rounded-lg hover:bg-blue-800">
          <PlusCircle size={16} /> Add Demo Loan
        </button>
      </div>
      {loans.length === 0 ? (
        <p className="text-gray-500 text-center py-8">No loans found. Add a demo loan to start.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b text-sm text-gray-500">
                <th className="pb-3 font-medium">Loan Title</th>
                <th className="pb-3 font-medium">Principal</th>
                <th className="pb-3 font-medium">Interest</th>
                <th className="pb-3 font-medium">EMI/mo</th>
                <th className="pb-3 font-medium">Risk</th>
                <th className="pb-3 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {loans.map((loan) => (
                <tr key={loan.id} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="py-4 text-gray-800 font-medium">{loan.title}</td>
                  <td className="py-4 text-gray-600">${loan.principal.toLocaleString()}</td>
                  <td className="py-4 text-gray-600">{loan.annual_interest_rate}%</td>
                  <td className="py-4 text-primary font-bold">${loan.monthly_emi}</td>
                  <td className="py-4">
                    <span className={`px-3 py-1 rounded-full text-xs font-semibold ${loan.risk_category === 'Low' ? 'bg-green-100 text-green-700' : loan.risk_category === 'Medium' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>
                      {loan.risk_category}
                    </span>
                  </td>
                  <td className="py-4 text-right">
                    <button onClick={() => onDownloadPdf(loan.id)} className="text-secondary hover:text-emerald-700 text-sm flex items-center justify-end gap-1 w-full">
                      <FileDown size={16} /> PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
