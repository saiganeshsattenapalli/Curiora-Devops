import { Component, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { useReducedMotion } from 'framer-motion'

function Orb({ active, reduced }) {
  const group = useRef()
  useFrame((_, delta) => {
    if (!reduced && group.current) {
      group.current.rotation.y += delta * (active ? 0.35 : 0.12)
      group.current.rotation.z += delta * 0.035
    }
  })
  return <group ref={group} rotation={[0.35, 0.2, 0.2]}>
    <mesh><icosahedronGeometry args={[1.05, 1]} /><meshStandardMaterial color="#62efc8" wireframe emissive="#23b78c" emissiveIntensity={0.6} /></mesh>
    <mesh><icosahedronGeometry args={[0.72, 1]} /><meshStandardMaterial color="#122f2b" metalness={0.65} roughness={0.3} flatShading /></mesh>
    {[0, Math.PI / 2, Math.PI / 4].map((angle, index) => <mesh key={angle} rotation={[angle, angle / 2, index]}><torusGeometry args={[1.38 + index * 0.08, 0.007, 6, 72]} /><meshBasicMaterial color={index === 0 ? '#82f5d3' : '#326e60'} /></mesh>)}
  </group>
}
class CoreBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <div className="orb-fallback">◇</div> : this.props.children }
}
export default function CurioCore({ active }) {
  const reduced = useReducedMotion()
  return <div className="orb-wrap" aria-hidden="true"><div className="orb-grid" /><CoreBoundary><Canvas dpr={[1, 1.5]} camera={{ position: [0, 0, 4.5], fov: 46 }} frameloop={reduced ? 'demand' : 'always'} fallback={<div className="orb-fallback">◇</div>} gl={{ antialias: true, powerPreference: 'low-power' }}><ambientLight intensity={1.5} /><pointLight position={[2, 3, 4]} intensity={12} color="#98ffe1" /><Orb active={active} reduced={reduced} /></Canvas></CoreBoundary><span className="orb-coordinate left">SYS / 001</span><span className="orb-coordinate right">REASON → ACT</span></div>
}
