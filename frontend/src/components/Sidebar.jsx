import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  FiHome, FiUsers, FiNavigation, FiMessageSquare,
  FiCalendar, FiCreditCard, FiX, FiDollarSign,
  FiSend, FiMessageCircle, FiBriefcase, FiMapPin, FiTruck,
  FiTag, FiAward
} from 'react-icons/fi';

// Only what the product actually does today: riders order a ride now or for
// later, driver and rider negotiate the fare, the fare is settled in cash, and
// the platform earns from driver subscriptions.
//
// Hidden rather than deleted — the routes and pages still exist, so restoring
// any of these is one line here:
//   Wallets, Payouts  — held balances and disbursements. Fares settle offline,
//                       so no money moves through the app to hold or pay out.
//   Payments          — was per-trip charges; subscription payments are shown
//                       on the Subscriptions page instead.
//   Companies         — corporate accounts, not part of this product.
//   Trips, Bookings   — the scheduled-trip marketplace (drivers publish trips
//                       with seats). Removed from the apps, so nothing feeds it.
const NAV = [
  { to: '/',              icon: FiHome,          label: 'Dashboard',     end: true },
  { to: '/users',         icon: FiUsers,         label: 'Users & Drivers' },
  { to: '/negotiations',  icon: FiNavigation,    label: 'Rides' },
  { to: '/subscriptions', icon: FiAward,         label: 'Subscriptions' },
  { to: '/chats',         icon: FiMessageCircle, label: 'Chats' },
  { to: '/vehicles',      icon: FiTruck,         label: 'Vehicles' },
  { to: '/vehicle-categories', icon: FiTruck,    label: 'Vehicle Categories' },
  { to: '/pricing',       icon: FiTag,           label: 'Pricing' },
  { to: '/route-stages',  icon: FiMapPin,        label: 'Route Stages' },
];

export default function Sidebar({ open, onClose }) {
  return (
    <>
      <div className="sidebar-overlay" onClick={onClose} />
      <nav className={`sidebar ${open ? 'sidebar--open' : ''}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">T</div>
          <div className="brand-info">
            <span className="brand-text">Truckfully</span>
            <span className="brand-tag">Admin Panel</span>
          </div>
          <button className="sidebar-close" onClick={onClose}><FiX /></button>
        </div>
        <ul className="sidebar-nav">
          {NAV.map(({ to, icon: Icon, label, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) => `nav-link ${isActive ? 'nav-link--active' : ''}`}
                onClick={onClose}
              >
                <Icon className="nav-icon" />
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="sidebar-footer">Truckfully © 2025</div>
      </nav>
    </>
  );
}
