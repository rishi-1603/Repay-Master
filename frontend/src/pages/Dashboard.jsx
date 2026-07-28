import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getLoans, createLoan, downloadReport } from '../services/api';
import Navbar from '../components/layout/Navbar';
import LoanTable from '../components/loans/LoanTable';
import LoanSimulator from '../components/loans/LoanSimulator';
import EMIChart from '../components/charts/EMIChart';
import AiAdvisor from '../components/chat/AiAdvisor';

export default function Dashboard({ setAuth }) {
  const [loans, setLoans] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    fetchLoans();
  }, []);

  const fetchLoans = async () => {
    try {
      const data = await getLoans();
      setLoans(data);
    } catch (err) {
      if (err.response?.status === 401) handleLogout();
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setAuth(false);
    navigate('/login');
  };

  const handleAddDemoLoan = async () => {
    await createLoan({
      title: 'Home Loan',
      principal: 250000,
      annual_interest_rate: 6.5,
      tenure_months: 240
    });
    fetchLoans();
  };

  const handleDownloadPdf = async (loanId) => {
    try {
      await downloadReport(loanId);
    } catch (e) {
      alert("Failed to download report");
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar onLogout={handleLogout} />
      <main className="flex-1 max-w-7xl w-full mx-auto p-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2">
          <LoanTable loans={loans} onAddDemo={handleAddDemoLoan} onDownloadPdf={handleDownloadPdf} />
          <EMIChart loans={loans} />
          <LoanSimulator loans={loans} />
        </div>
        <div className="lg:col-span-1">
          <AiAdvisor loans={loans} />
        </div>
      </main>
    </div>
  );
}
