import React from 'react';
import { Activity, LogOut } from 'lucide-react';

export default function Navbar({ onLogout }) {
  return (
    <nav className="bg-card shadow-sm border-b border-gray-800 px-8 py-4 flex justify-between items-center">
      <h1 className="text-2xl font-bold text-white flex items-center gap-2">
        <Activity className="text-primary" /> RepayMaster AI
      </h1>
      <button onClick={onLogout} className="text-gray-400 hover:text-red-500 flex items-center gap-2 font-medium">
        <LogOut size={20} /> Logout
      </button>
    </nav>
  );
}
