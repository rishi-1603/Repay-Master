import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createLoan, getLoanAnalytics } from '../services/api';
import Navbar from '../components/layout/Navbar';
import LoanForm from '../components/loans/LoanForm';
import Recommendations from '../components/loans/Recommendations';
import MLRiskAssessment from '../components/charts/MLRiskAssessment';
import FinancialOverview from '../components/charts/FinancialOverview';
import AiAdvisor from '../components/chat/AiAdvisor';

export default function Dashboard({ setAuth }) {
  const [activeAnalytics, setActiveAnalytics] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('token');
    setAuth(false);
    navigate('/login');
  };

  const handleCreateLoan = async (formData) => {
    try {
      setIsLoading(true);
      // Create the loan
      const newLoan = await createLoan(formData);
      // Fetch detailed analytics for it
      const analytics = await getLoanAnalytics(newLoan.id);
      setActiveAnalytics(analytics);
    } catch (err) {
      if (err.response?.status === 401) {
        handleLogout();
      } else {
        alert("Failed to process loan data.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-dark flex flex-col font-sans">
      <Navbar onLogout={handleLogout} />
      
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-8">
        
        {/* Main Input Form */}
        <LoanForm onCreateLoan={handleCreateLoan} />

        {isLoading && (
          <div className="text-center text-primary my-12 animate-pulse">
            Analyzing Financial Profile & Running ML Models...
          </div>
        )}

        {/* Dashboard Analytics (Only visible after a loan is created) */}
        {activeAnalytics && !isLoading && (
          <div className="animate-fade-in">
            <Recommendations analytics={activeAnalytics} />
            <MLRiskAssessment analytics={activeAnalytics} />
            <FinancialOverview analytics={activeAnalytics} />
            
            <div className="mt-8">
              <AiAdvisor loans={[]} /> 
            </div>
          </div>
        )}

      </main>
    </div>
  );
}
