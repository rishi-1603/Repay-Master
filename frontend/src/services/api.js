import axios from 'axios';

const API_URL = "https://repay-master.onrender.com/api/v1";

export const api = axios.create({
  baseURL: API_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const login = async (username, password) => {
  const response = await api.post('/auth/login', new URLSearchParams({
    username,
    password,
  }));
  if (response.data.access_token) {
    localStorage.setItem('token', response.data.access_token);
  }
  return response.data;
};

export const signup = async (email, password, full_name) => {
  const response = await api.post('/auth/signup', {
    email,
    password,
    full_name
  });
  return response.data;
};

export const getLoans = async () => {
  const response = await api.get('/loans/');
  return response.data;
};

export const createLoan = async (loan) => {
  const response = await api.post('/loans/', loan);
  return response.data;
};

export const getLoanAnalytics = async (loanId) => {
  const response = await api.get(`/loans/${loanId}/analytics`);
  return response.data;
};

export const chatWithAI = async (message, context = null) => {
  const response = await api.post('/ai/chat', { message, context });
  return response.data;
};

export const compareBanks = async (principal, tenure_months) => {
  const response = await api.get('/loans/compare', { params: { principal, tenure_months } });
  return response.data;
};

export const optimizePrepayment = async (principal, annual_interest_rate, tenure_months, extra_payment) => {
  const response = await api.post('/loans/optimize', null, { 
    params: { principal, annual_interest_rate, tenure_months, extra_payment } 
  });
  return response.data;
};

export const downloadReport = async (loanId) => {
  const response = await api.get(`/reports/pdf/${loanId}`, { responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `Report_Loan_${loanId}.pdf`);
  document.body.appendChild(link);
  link.click();
};
