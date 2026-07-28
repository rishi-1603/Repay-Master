import React from 'react';
import { Activity, LogOut } from 'lucide-react';

export default function Navbar({ onLogout }) {
  return (
    <nav className="bg-white shadow-sm border-b px-8 py-4 flex justify-between items-center">
      <h1 className="text-2xl font-bold text-primary flex items-center gap-2">
        <Activity className="text-secondary" /> RepayMaster AI
      </h1>
      <button onClick={onLogout} className="text-gray-500 hover:text-red-500 flex items-center gap-2 font-medium">
        <LogOut size={20} /> Logout
      </button>
    </nav>
  );
}
