import { createContext, useContext } from 'react'
export const RevealContext = createContext(false)
export const useReveal = () => useContext(RevealContext)
